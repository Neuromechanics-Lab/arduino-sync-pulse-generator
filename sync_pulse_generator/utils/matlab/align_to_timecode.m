function result = align_to_timecode(frames, varargin)
% ALIGN_TO_TIMECODE Place a recording on the generator's own timeline.
%
%   result = align_to_timecode(frames)
%   result = align_to_timecode(decode_timecode(e.time))
%
%   Converts decoded timecode frames into the mapping between RECORDING time
%   and GENERATOR time, so a recording can be located absolutely rather than
%   only relative to another recording.
%
%   WHAT A RUN IS, AND WHY IT MATTERS
%
%   The generator's elapsed clock is not a wall clock. It counts from the
%   start of the current RUN, and every run start increments the persistent
%   run ID. A run starts when:
%
%       * the box boots in FREE RUN mode (output begins immediately);
%       * a trigger edge arrives on TRIG IN while in TRIG RUN mode
%         (output is held LOW until then, so elapsed 0 IS the trigger);
%       * the mode switch is moved to FREE RUN;
%       * a serial 'start' or 'restart' command is issued.
%
%   So elapsed_s means "seconds since this run began", and what began the run
%   depends on the mode. In FREE RUN, elapsed 0 is power-up. In TRIG RUN,
%   elapsed 0 is the trigger pulse - which is the useful case for starting
%   several devices together from one master pulse.
%
%   Because the run ID changes at every one of those events, TWO RECORDINGS
%   SHARE A TIMELINE ONLY IF THEIR RUN IDS MATCH. Comparing elapsed values
%   across different run IDs is meaningless: they are counted from different
%   zeros. This function therefore treats a run ID change as a hard boundary
%   and reports each run separately rather than fitting through it.
%
%   ANCHOR ACCURACY
%
%   Frames start EXACTLY on the interval tick (the firmware cuts the random
%   segment short and holds LOW for a lead-in), so every anchor is exact:
%   t_rec of a frame IS elapsed_s of generator time, to the millisecond.
%   Offsets (elapsed - t_rec) should therefore agree across all frames to
%   within the recorder's edge-timing resolution (ANCHOR_TOL_MS = 10):
%
%     * the offset is the mean of all anchors;
%     * drift is a least-squares slope through all anchors, reported only
%       when it both exceeds the anchor tolerance over the span observed and
%       clears the slope's own noise floor by 3x; otherwise drift_ppm is 0
%       and drift_resolvable is false;
%     * residuals above ANCHOR_TOL_MS about the fit mean a frame was
%       mis-decoded or the recorder's timing is coarser than expected.
%
%   Name-Value:
%       'require_ok'  - Ignore checksum-failed frames (default true)
%       'expect_run'  - Only accept this run ID, ignoring others (default [])
%       'max_pulse_ms'- Accepted for backward compatibility and IGNORED. It
%                       parameterised the emission jitter of firmware that
%                       emitted frames late; frames now start on the tick.
%
%   Output struct:
%       .n_runs         - Distinct run IDs present
%       .run_ids        - The run IDs, in order of first appearance
%       .runs           - Struct array, one per run:
%           .run_id
%           .n_frames
%           .t_rec_first / .t_rec_last   - Recording-time span (s)
%           .elapsed_first / .elapsed_last
%           .offset_s     - Best-fit generator_time - recording_time
%           .drift_ppm    - Clock rate mismatch in ppm, or 0 when the record
%                           is too short to resolve any
%           .drift_resolvable - Whether drift_ppm means anything
%           .residual_ms  - Worst frame residual against the fit (ms)
%       .primary        - The run covering the most frames (usually the one
%                         you want); same fields as an entry in .runs
%       .offset_s       - Convenience copy of .primary.offset_s
%       .to_generator   - Function handle: recording time -> generator time
%       .to_recording   - Function handle: generator time -> recording time
%       .warnings       - Cell array of quality notes
%
%   Example:
%       e = detect_edges(rec.data(:, ch), rec.fs);
%       f = decode_timecode(e.time(e.polarity > 0));
%       a = align_to_timecode(f);
%       fprintf('run %d, recording starts at generator t = %.3f s\n', ...
%               a.primary.run_id, a.to_generator(0));
%
%   See also DECODE_TIMECODE, DETECT_EDGES, SHIFT_TIMESTAMPS.

    ANCHOR_TOL_MS = 10;   % anchors agree to within recorder edge timing

    p = inputParser;
    addParameter(p, 'require_ok',   true);
    addParameter(p, 'expect_run',   []);
    % Accepted so existing calls keep working; deliberately never read. It
    % parameterised the emission jitter of firmware that started frames late,
    % which the lead-in removed - frames now begin exactly on the tick.
    addParameter(p, 'max_pulse_ms', 500);
    parse(p, varargin{:});
    o = p.Results;

    if isempty(frames)
        error('align_to_timecode:noFrames', ...
              ['No timecode frames were decoded. Either the generator had ', ...
               'timecode disabled (DEFAULT_TC_ENABLED 0), the recording is ', ...
               'shorter than one frame interval, or the edge detector missed ', ...
               'the frame pulses - they are only %d ms wide.'], 5);
    end

    if o.require_ok
        frames = frames([frames.ok]);
        if isempty(frames)
            error('align_to_timecode:allBadChecksums', ...
                  ['Frames were found but every checksum failed. The frame ', ...
                   'timing constants here may not match the firmware that ', ...
                   'produced the recording - check TC_* in config.h.']);
        end
    end

    if ~isempty(o.expect_run)
        frames = frames([frames.run_id] == o.expect_run);
        if isempty(frames)
            error('align_to_timecode:runNotFound', ...
                  'No frames carry run ID %d.', o.expect_run);
        end
    end

    warnings = {};

    ids = [frames.run_id];
    uniq = unique(ids, 'stable');

    runs = struct('run_id', {}, 'n_frames', {}, ...
                  't_rec_first', {}, 't_rec_last', {}, ...
                  'elapsed_first', {}, 'elapsed_last', {}, ...
                  'offset_s', {}, 'drift_ppm', {}, ...
                  'drift_resolvable', {}, 'residual_ms', {});

    for k = 1:numel(uniq)
        sel = frames(ids == uniq(k));
        t   = [sel.t_rec]';
        el  = [sel.elapsed_s]';

        % Anchors are exact (frames start on the tick): every frame carries
        % equal weight.
        [offset, drift_ppm, residual_ms, resolvable] = local_anchor_fit(t, el);

        runs(end+1) = struct( ...
            'run_id',           uniq(k), ...
            'n_frames',         numel(sel), ...
            't_rec_first',      min(t), ...
            't_rec_last',       max(t), ...
            'elapsed_first',    min(el), ...
            'elapsed_last',     max(el), ...
            'offset_s',         offset, ...
            'drift_ppm',        drift_ppm, ...
            'drift_resolvable', resolvable, ...
            'residual_ms',      residual_ms); %#ok<AGROW>
    end

    % The run with the most frames is the one the recording is mostly about.
    [~, best] = max([runs.n_frames]);
    primary = runs(best);

    if numel(uniq) > 1
        warnings{end+1} = sprintf( ...
            ['%d different run IDs appear in this recording (%s). The ', ...
             'generator restarted mid-recording - a trigger arrived, the ', ...
             'mode switch moved, or it was restarted over serial. Each run ', ...
             'counts elapsed time from its own zero, so they CANNOT be ', ...
             'placed on one timeline. Run %d (%d frames) was used; split ', ...
             'the recording at the boundary to use the others.'], ...
            numel(uniq), strjoin(arrayfun(@(x) sprintf('%d', x), uniq, ...
            'UniformOutput', false), ', '), primary.run_id, primary.n_frames);
    end

    if primary.n_frames < 2
        warnings{end+1} = ['Only one frame was decoded, so the offset rests ', ...
            'on a single anchor and no drift estimate is possible. Record ', ...
            'for at least two frame intervals for a checkable alignment.'];
    end

    span = max(primary.t_rec_last - primary.t_rec_first, 1e-9);
    if primary.drift_resolvable
        implied_ms = abs(primary.drift_ppm) * span / 1000;
        warnings{end+1} = sprintf( ...
            ['Clock rate differs by %.0f ppm between the generator and the ', ...
             'recorder (%.1f ms per minute, %.0f ms over the %.0f s ', ...
             'observed). A constant offset will not hold across a long ', ...
             'trial.'], primary.drift_ppm, primary.drift_ppm * 60 / 1000, ...
            implied_ms, span);
    end

    if primary.residual_ms > ANCHOR_TOL_MS
        warnings{end+1} = sprintf( ...
            ['Frame anchors scatter by up to %.0f ms about the fit, more ', ...
             'than the %.0f ms anchor tolerance. Frames start exactly on ', ...
             'the tick, so this means a frame was mis-decoded or the ', ...
             'recorder''s edge timing is coarser than expected.'], ...
            primary.residual_ms, ANCHOR_TOL_MS);
    end

    offset = primary.offset_s;

    result.n_runs       = numel(uniq);
    result.run_ids      = uniq;
    result.runs         = runs;
    result.primary      = primary;
    result.offset_s     = offset;
    result.to_generator = @(t_rec) t_rec + offset;
    result.to_recording = @(t_gen) t_gen - offset;
    result.warnings     = warnings;
end


% =========================================================================
function [offset, drift_ppm, resid_ms, resolvable] = local_anchor_fit(t, el)
% Offset + drift from EXACT anchors. Frames start on the tick, so all anchors
% carry equal weight: offset = mean(elapsed - t_rec), drift = least-squares
% slope of the offsets against recording time. drift_ppm is 0 unless
% resolvable: it must exceed the anchor tolerance over the span observed AND
% clear the slope's own noise floor by 3x.

    ANCHOR_TOL_MS = 10;
    drift_ppm = 0; resid_ms = 0; resolvable = false;

    n = numel(t);
    offs = el - t;
    offset = mean(offs);
    span = 0;
    if n > 0
        span = max(t) - min(t);
    end
    if n < 3 || span <= 0
        if n > 1
            resid_ms = (max(offs) - min(offs)) * 1000;
        end
        return;
    end

    mx = mean(t);
    sxx = sum((t - mx).^2);
    slope = sum((t - mx) .* (offs - offset)) / sxx;
    intercept = offset - slope * mx;
    resid = offs - (slope * t + intercept);
    resid_ms = max(abs(resid)) * 1000;
    drift_est = slope * 1e6;

    slope_noise_ppm = ((max(resid) - min(resid)) / span) * 1e6;
    resolvable = (abs(drift_est) * span / 1000 > ANCHOR_TOL_MS) && ...
                 (abs(drift_est) > 3 * slope_noise_ppm);
    if resolvable
        drift_ppm = drift_est;
    end
end

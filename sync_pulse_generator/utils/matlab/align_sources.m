function result = align_sources(sources, varargin)
% ALIGN_SOURCES Align any number of recordings onto one timeline.
%
%   result = align_sources(sources)
%   result = align_sources(sources, 'mode', 'stitch', 'target_fs', 1000)
%
%   Several devices record the same experiment, each with its own clock, its
%   own start time, its own sample rate, and its own way of reporting the
%   sync signal - one gives a continuous analog waveform, another only the
%   timestamps of rising edges, a third only falling edges. Some drop
%   frames. None agree on when zero was.
%
%   The approach is NOT to align recordings to each other. The generator's
%   output is fully determined by (seed, config), so the intended waveform
%   can be regenerated from code. Every recording is locked INDEPENDENTLY to
%   that template, which makes alignment transitive: any two recordings are
%   related through the template, with no reference device, no pairwise
%   matrix, and no accumulated error. Recordings that never overlap in
%   wall-clock time still land on one timeline.
%
%   Edge-only inputs work natively because the template is itself just a
%   list of transition times, and so is a rising-edge-only recording. A
%   continuous signal passes through DETECT_EDGES first to become one.
%
%   INPUT
%   sources - struct array, one per recording, with fields:
%       .name       Label
%       .edges      Transition times in seconds, this recording's own clock
%       .polarity   +1/-1 per edge, or [] if unknown          (optional)
%       .fs         Nominal sample rate                       (optional)
%       .data       samples x channels                        (optional)
%       .labels     1xN cell of channel names                 (optional)
%       .time       Per-sample times, own clock               (optional)
%     Build one with SOURCE_FROM_CONTINUOUS or SOURCE_FROM_EDGES.
%
%   Name-Value:
%       'mode'      'lags' | 'global_time' (default) | 'stitch'
%                     lags        - fits only; no data touched
%                     global_time - each recording keeps its own samples and
%                                   rate, and gains a global time vector
%                     stitch      - one merged table on a common time base
%       'resample'  'linear' (default) | 'nearest' | 'decimate'
%                     'nearest' for marker/categorical channels that must
%                     not be averaged or filtered
%       'target_fs' Common rate for stitch. Default: the FASTEST source
%                   rate, which upsamples the slower ones rather than
%                   discarding detail from the faster ones.
%       'run_id'    Generator run. Default [] means read it from the
%                   recordings' own timecode frames.
%       'duration'  Template length in seconds. Default covers the data.
%
%   OUTPUT struct:
%       .fits        Struct array, one per source (see below)
%       .global_time Struct: .(name) = global time vector
%       .table       stitch only: .time, .columns, .fs
%       .warnings    Cell array of plain-language notes
%
%   Each .fits entry:
%       .name .ok .offset_s .rate .drift_ppm .n_edges .n_matched
%       .match_rate .rms_ms .confidence .run_id .source_of_lock
%       .segments .drops .frame_gaps .note
%
%   See also DETECT_EDGES, DECODE_TIMECODE, SOURCE_FROM_CONTINUOUS.

    p = inputParser;
    addParameter(p, 'mode',      'global_time');
    addParameter(p, 'resample',  'linear');
    addParameter(p, 'target_fs', []);
    addParameter(p, 'run_id',    []);
    addParameter(p, 'duration',  []);
    addParameter(p, 'tol_ms',    6);
    addParameter(p, 'gap_factor', 3);
    parse(p, varargin{:});
    o = p.Results;

    if isempty(sources)
        error('align_sources:noSources', 'No sources given.');
    end
    mode = lower(o.mode);
    if ~ismember(mode, {'lags', 'global_time', 'stitch'})
        error('align_sources:badMode', ...
              'mode must be ''lags'', ''global_time'', or ''stitch''.');
    end

    tol_s = o.tol_ms / 1000;

    % --- Template length ---------------------------------------------------
    span = 0;
    for k = 1:numel(sources)
        if ~isempty(sources(k).edges)
            span = max(span, max(sources(k).edges));
        end
    end
    duration = o.duration;
    if isempty(duration)
        duration = max(60, span * 1.5 + 60);
    end

    % --- Discover the run BEFORE building the template ---------------------
    % Frame payloads encode the run ID, so a template built for the wrong run
    % has the right pseudo-random train but different frame bits: offsets
    % still come out right (the frames supply them) while a large fraction of
    % edges fail to pair. Ask the recordings which run they are.
    run_id = o.run_id;
    if isempty(run_id)
        votes = [];
        for k = 1:numel(sources)
            rid = local_frame_run(sources(k));
            if ~isempty(rid), votes(end+1) = rid; end %#ok<AGROW>
        end
        if isempty(votes)
            run_id = 1;
        else
            run_id = mode_of(votes);
        end
    end

    tmpl = align_template(duration, run_id);

    % --- Lock each source ---------------------------------------------------
    fits = struct('name', {}, 'ok', {}, 'offset_s', {}, 'rate', {}, ...
                  'drift_ppm', {}, 'n_edges', {}, 'n_matched', {}, ...
                  'match_rate', {}, 'rms_ms', {}, 'confidence', {}, ...
                  'run_id', {}, 'source_of_lock', {}, 'segments', {}, ...
                  'drops', {}, 'frame_gaps', {}, 'anchors', {}, ...
                  'nonlinear', {}, 'note', {});
    for k = 1:numel(sources)
        fits(k) = align_lock(sources(k), tmpl, tol_s); %#ok<AGROW>
    end

    warnings = {};

    % --- Run identity is a hard boundary ------------------------------------
    ids = [];
    for k = 1:numel(fits)
        if ~isempty(fits(k).run_id), ids(end+1) = fits(k).run_id; end %#ok<AGROW>
    end
    uniq = unique(ids);
    if numel(uniq) > 1
        parts = cell(1, numel(uniq));
        for u = 1:numel(uniq)
            names = {};
            for k = 1:numel(fits)
                if isequal(fits(k).run_id, uniq(u)), names{end+1} = fits(k).name; end %#ok<AGROW>
            end
            parts{u} = sprintf('run %d: %s', uniq(u), strjoin(names, ', '));
        end
        warnings{end+1} = sprintf(['Recordings come from %d DIFFERENT ', ...
            'generator runs (%s). Each run restarts the elapsed clock from ', ...
            'its own zero, so these cannot be placed on one timeline. Split ', ...
            'them by run and align each group separately.'], ...
            numel(uniq), strjoin(parts, '; '));
    end

    for k = 1:numel(fits)
        f = fits(k);
        if ~f.ok
            warnings{end+1} = sprintf('%s: %s', f.name, f.note); %#ok<AGROW>
            continue;
        end
        if f.confidence < 0.3
            warnings{end+1} = sprintf(['%s: weak lock (confidence %.2f). ', ...
                'The winning alignment was proposed by only a minority of ', ...
                'windows - check before relying on it.'], f.name, f.confidence); %#ok<AGROW>
        end
        if f.match_rate < 0.5
            warnings{end+1} = sprintf(['%s: only %.0f%% of its edges matched ', ...
                'the template. Expect missing or spurious edges.'], ...
                f.name, 100*f.match_rate); %#ok<AGROW>
        end
        if abs(f.drift_ppm) > 1000
            warnings{end+1} = sprintf(['%s: clock differs from the generator ', ...
                'by %+.0f ppm (%.0f ms per hour).'], ...
                f.name, f.drift_ppm, f.drift_ppm*3.6); %#ok<AGROW>
        end
        for d = 1:size(f.drops, 1)
            warnings{end+1} = sprintf(['%s: timeline steps by %+.1f ms at ', ...
                't=%.2f s - the recorder lost count there.'], ...
                f.name, f.drops(d,2), f.drops(d,1)); %#ok<AGROW>
        end
        for g = 1:size(f.frame_gaps, 1)
            warnings{end+1} = sprintf(['%s: %d timecode frame(s) missing ', ...
                'between t=%.2f and t=%.2f s - data is absent there.'], ...
                f.name, f.frame_gaps(g,3), f.frame_gaps(g,1), f.frame_gaps(g,2)); %#ok<AGROW>
        end
    end

    result.mode     = mode;
    result.run_id   = run_id;
    result.fits     = fits;
    result.warnings = warnings;
    result.global_time = struct();

    if strcmp(mode, 'lags')
        return;
    end

    % --- global time --------------------------------------------------------
    for k = 1:numel(sources)
        if ~fits(k).ok, continue; end
        st = local_sample_times(sources(k));
        if isempty(st), st = sources(k).edges(:); end
        fld = matlab.lang.makeValidName(sources(k).name);
        result.global_time.(fld) = align_apply(fits(k), st);
    end

    if strcmp(mode, 'global_time')
        return;
    end

    % --- stitch --------------------------------------------------------------
    use = [];
    for k = 1:numel(sources)
        if fits(k).ok && ~isempty(sources(k).data), use(end+1) = k; end %#ok<AGROW>
    end
    if isempty(use)
        error('align_sources:nothingToStitch', ...
              ['Stitch needs at least one source with data that locked to ', ...
               'the template.']);
    end

    target_fs = o.target_fs;
    if isempty(target_fs)
        rates = [];
        for k = use
            if ~isempty(sources(k).fs), rates(end+1) = sources(k).fs; end %#ok<AGROW>
        end
        if isempty(rates), target_fs = 1000; else, target_fs = max(rates); end
    end

    t0 = inf; t1 = -inf;
    for k = use
        g = result.global_time.(matlab.lang.makeValidName(sources(k).name));
        t0 = min(t0, g(1)); t1 = max(t1, g(end));
    end
    common = (t0 : 1/target_fs : t1)';

    columns = struct();
    for k = use
        src = sources(k);
        g = result.global_time.(matlab.lang.makeValidName(src.name));
        data = src.data;
        if isvector(data), data = data(:); end
        labels = src.labels;
        if isempty(labels)
            labels = arrayfun(@(i) sprintf('ch%d', i), 1:size(data,2), ...
                              'UniformOutput', false);
        end
        gap_s = [];
        if ~isempty(src.fs), gap_s = o.gap_factor / src.fs; end
        for c = 1:size(data, 2)
            nm = matlab.lang.makeValidName(sprintf('%s_%s', src.name, labels{c}));
            columns.(nm) = align_resample(g, data(:,c), common, ...
                                          o.resample, gap_s, target_fs, src.fs);
        end
    end

    result.table = struct('time', common, 'columns', columns, ...
                          'fs', target_fs, 'n', numel(common));
end


% =========================================================================
function m = mode_of(v)
    u = unique(v);
    c = arrayfun(@(x) sum(v == x), u);
    [~, i] = max(c);
    m = u(i);
end


function rid = local_frame_run(src)
% Run ID from decoded timecode frames, or [] if none decode.
    rid = [];
    if numel(src.edges) < 55, return; end
    [frames, rid] = align_frames(src);            %#ok<ASGLU>
end


function t = local_sample_times(src)
    t = [];
    if isfield(src, 'time') && ~isempty(src.time)
        t = src.time(:);
    elseif ~isempty(src.data) && ~isempty(src.fs)
        n = size(src.data, 1);
        t = (0:n-1)' / src.fs;
    end
end

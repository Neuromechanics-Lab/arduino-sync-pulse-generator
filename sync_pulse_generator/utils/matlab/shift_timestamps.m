function out = shift_timestamps(rec, delay_ms, varargin)
% SHIFT_TIMESTAMPS Correct a recording's timestamps by a measured delay.
%
%   out = shift_timestamps(rec, 22.99)
%   out = shift_timestamps(rec, d.delay_ms, 'channels', emg_idx)
%   out = shift_timestamps(rec, d, 'resample', true)
%
%   Applies a measured delay to a recording so it lines up with the device
%   it was measured against. Works on however many channels the recording
%   carries - the whole set by default, or a chosen subset.
%
%   delay_ms is either a number of milliseconds or an EDGE_DELAY result
%   struct, in which case its .delay_ms field is used.
%
%   Sign convention, matching EDGE_DELAY: a positive delay means this
%   recording arrived LATE, so its timestamps are shifted EARLIER (the
%   sample labelled t actually happened at t - delay). Pass 'invert' to
%   reverse that if your delay was measured the other way round.
%
%   Two correction styles:
%
%     Timestamp shift (default) - rewrites the time vector and leaves the
%       samples untouched. Nothing is interpolated, so no data is altered.
%       The recording then starts at a non-zero time, which every downstream
%       tool here handles.
%
%     Resample ('resample', true) - keeps the original time base and shifts
%       the DATA onto it by interpolation. Use when something downstream
%       demands that all recordings share one time grid. Interpolation is a
%       lossy operation, so this is not the default.
%
%   Name-Value:
%       'channels' - Indices to shift (default: all)
%       'resample' - true to interpolate instead of relabelling (default false)
%       'invert'   - true to flip the sign of the correction (default false)
%       'method'   - Interpolation method for resample (default 'linear')
%
%   Output: a copy of rec with
%       .time          - Corrected time vector
%       .data          - Unchanged, or interpolated when 'resample'
%       .shift_applied_ms
%       .shift_channels
%       .original_time - The time vector before correction
%
%   See also EDGE_DELAY, ALIGN_RECORDINGS.

    p = inputParser;
    addParameter(p, 'channels', []);
    addParameter(p, 'resample', false);
    addParameter(p, 'invert',   false);
    addParameter(p, 'method',   'linear');
    parse(p, varargin{:});
    o = p.Results;

    if isstruct(delay_ms)
        if ~isfield(delay_ms, 'delay_ms')
            error('shift_timestamps:badDelay', ...
                  'Struct input must be an edge_delay result with a delay_ms field.');
        end
        d_ms = delay_ms.delay_ms;
    else
        if ~isscalar(delay_ms) || ~isfinite(delay_ms)
            error('shift_timestamps:badDelay', ...
                  'delay_ms must be a finite scalar or an edge_delay result.');
        end
        d_ms = delay_ms;
    end

    if o.invert
        d_ms = -d_ms;
    end
    d_s = d_ms / 1000;

    out = rec;

    if ~isfield(rec, 'time') || isempty(rec.time)
        if ~isfield(rec, 'fs') || isempty(rec.fs)
            error('shift_timestamps:noTime', ...
                  'Recording needs either a .time vector or an .fs field.');
        end
        rec.time = (0:size(rec.data,1)-1)' / rec.fs;
    end
    out.original_time = rec.time;

    n_ch = size(rec.data, 2);
    if isempty(o.channels)
        ch = 1:n_ch;
    else
        ch = o.channels(:)';
        if any(ch < 1) || any(ch > n_ch)
            error('shift_timestamps:badChannels', ...
                  'Channel indices must be between 1 and %d.', n_ch);
        end
    end

    if ~o.resample
        % Relabel time. When only a subset is being corrected, the recording
        % can no longer be described by one time vector, so the shifted
        % channels are split out rather than silently mislabelled.
        if numel(ch) == n_ch
            out.time = rec.time - d_s;
        else
            out.time = rec.time;
            out.shifted_time = rec.time - d_s;
            warning('shift_timestamps:partial', ...
                    ['Only %d of %d channels were shifted. The corrected time ', ...
                     'base for those channels is in .shifted_time; .time still ', ...
                     'describes the rest.'], numel(ch), n_ch);
        end
    else
        % Move the data instead. The true time of each sample is t - d_s;
        % resample that onto the original grid.
        src = rec.time - d_s;
        dst = rec.time;
        data = rec.data;
        for k = ch
            v = double(data(:, k));
            good = isfinite(v);
            if ~any(good)
                continue;
            end
            data(:, k) = interp1(src(good), v(good), dst, o.method, NaN);
        end
        out.data = data;
        out.time = dst;
    end

    out.shift_applied_ms = d_ms;
    out.shift_channels   = ch;
end

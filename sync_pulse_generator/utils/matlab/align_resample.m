function out = align_resample(src_t, src_v, dst_t, how, gap_s, target_fs, src_fs)
% ALIGN_RESAMPLE Put one channel on a common time base.
%
%   Never interpolates across a gap: where the source has no samples within
%   gap_s, the output is NaN. Inventing values across a dropped chunk would
%   silently manufacture data.
%
%   how:
%     'linear'   interpolate (anti-aliased first when decimating)
%     'nearest'  nearest sample - for markers and categorical channels that
%                must not be averaged or filtered
%     'decimate' explicit anti-aliased downsample
%
%   Downsampling without a low-pass is silent corruption, not merely
%   inaccuracy: a 230 Hz tone taken from 2000 Hz to 100 Hz reappears at FULL
%   amplitude disguised as 30 Hz, indistinguishable from real signal.
%
%   See also ALIGN_SOURCES.

    if nargin < 4 || isempty(how),      how = 'linear'; end
    if nargin < 5,                      gap_s = [];     end
    if nargin < 6,                      target_fs = []; end
    if nargin < 7,                      src_fs = [];    end

    src_t = src_t(:); src_v = double(src_v(:)); dst_t = dst_t(:);
    good = isfinite(src_t) & isfinite(src_v);
    if sum(good) < 2
        out = nan(size(dst_t));
        return;
    end
    st = src_t(good); sv = src_v(good);

    % Anti-alias before decimating. 'nearest' is exempt: it exists to keep
    % marker values intact, and filtering them would invent levels that were
    % never recorded.
    if ~strcmpi(how, 'nearest') && ~isempty(target_fs)
        sv = local_antialias(st, sv, target_fs, src_fs);
    end

    if strcmpi(how, 'nearest')
        out = interp1(st, sv, dst_t, 'nearest', NaN);
    else
        out = interp1(st, sv, dst_t, 'linear', NaN);
    end

    out(dst_t < st(1) | dst_t > st(end)) = NaN;

    if ~isempty(gap_s) && numel(st) > 1
        d = diff(st);
        for i = find(d > gap_s)'
            out(dst_t > st(i) & dst_t < st(i+1)) = NaN;
        end
    end
end


function v = local_antialias(t, v, target_fs, src_fs)
% Zero-phase low-pass ahead of a decimation, so the filter adds no lag -
% which matters in a module whose whole purpose is timing.
    if isempty(src_fs)
        d = diff(t);
        d = d(isfinite(d) & d > 0);
        if isempty(d), return; end
        src_fs = 1 / median(d);
    end
    if target_fs >= src_fs * 0.98
        return;                        % not decimating
    end
    if exist('butter', 'file') ~= 2 && exist('butter', 'builtin') ~= 5
        warning('align_resample:noFilter', ...
                ['Decimating %g Hz to %g Hz without a filter (butter is ', ...
                 'unavailable). Content above %g Hz will fold back into the ', ...
                 'result at full amplitude.'], src_fs, target_fs, target_fs/2);
        return;
    end
    wn = (0.45 * target_fs) / (src_fs / 2);
    if wn <= 0 || wn >= 1, return; end
    [b, a] = butter(4, wn, 'low');
    if numel(v) > 3 * max(numel(a), numel(b))
        v = filtfilt(b, a, v);
    end
end

function out = process_emg(signal, fs, varargin)
% PROCESS_EMG Standard surface-EMG processing chain.
%
%   out = process_emg(x, fs)
%   out = process_emg(x, fs, 'band', [20 450], 'notch', 60)
%
%   Runs the conventional pipeline and returns EVERY intermediate stage, so
%   any step can be plotted to see where a signal goes wrong:
%
%       raw -> detrend -> bandpass -> (notch) -> rectify -> envelope
%
%   Stage notes:
%     detrend   Removes the DC offset the amplifier adds.
%     bandpass  4th-order zero-phase Butterworth, default 20-450 Hz. The low
%               cut removes motion artefact, the high cut sits below Nyquist
%               and above the EMG power band. Applied with filtfilt so the
%               filter adds no phase lag - important here, because a lag
%               would corrupt the very timing this toolbox measures.
%     notch     Optional mains rejection. Off by default: a good bandpass
%               plus decent electrode contact usually makes it unnecessary,
%               and a notch removes real signal at the same frequency.
%     rectify   Full-wave (absolute value).
%     envelope  Zero-phase low-pass of the rectified signal (default 4 Hz),
%               the usual linear envelope. An RMS envelope over a moving
%               window is also returned.
%
%   Name-Value:
%       'band'      - [low high] Hz bandpass, [] to skip (default [20 450])
%       'order'     - Butterworth order, per direction (default 4)
%       'notch'     - Mains frequency in Hz, [] or 0 to skip (default [])
%       'notch_q'   - Notch quality factor (default 30)
%       'envelope'  - Envelope low-pass in Hz, [] to skip (default 4)
%       'rms_window'- RMS window in ms (default 100)
%       'mvc'       - Divide envelope by this to normalise, [] to skip
%
%   Output struct:
%       .raw .detrended .filtered .rectified .envelope .rms
%       .fs .time
%       .mvc_percent  - Envelope as % MVC, when 'mvc' was supplied
%       .quality      - Substruct of checks (see below)
%       .warnings     - Cell array of plain-language quality notes
%
%   The .quality substruct reports:
%       .flat          - true when the channel never moves (nothing plugged in)
%       .saturated     - true when many samples sit at the extremes (a
%                        disconnected sensor rails at the supply limits, and
%                        looks like a huge signal unless checked)
%       .frac_at_rail  - Fraction of samples at the extremes
%       .snr_estimate  - Peak envelope over baseline envelope
%       .mains_ratio   - Power at the mains frequency over its neighbours
%
%   See also DETECT_EDGES, LOAD_C3D_ANALOG, PLOT_SYNC_CHECK.

    p = inputParser;
    addParameter(p, 'band',       [20 450]);
    addParameter(p, 'order',      4);
    addParameter(p, 'notch',      []);
    addParameter(p, 'notch_q',    30);
    addParameter(p, 'envelope',   4);
    addParameter(p, 'rms_window', 100);
    addParameter(p, 'mvc',        []);
    parse(p, varargin{:});
    o = p.Results;

    x = double(signal(:));
    n = numel(x);
    if n < 10
        error('process_emg:tooShort', 'Signal needs at least 10 samples.');
    end
    nyq = fs / 2;

    out.raw  = x;
    out.fs   = fs;
    out.time = (0:n-1)' / fs;

    % --- Quality first, on the raw signal ---------------------------------
    out.quality = local_quality(x, fs, o.notch);

    % --- Detrend -----------------------------------------------------------
    y = x - mean(x);
    out.detrended = y;

    % --- Bandpass ----------------------------------------------------------
    if ~isempty(o.band) && numel(o.band) == 2
        lo = o.band(1); hi = min(o.band(2), 0.99 * nyq);
        if lo >= hi
            error('process_emg:badBand', ...
                  'Bandpass [%g %g] is invalid at fs=%g Hz.', o.band(1), o.band(2), fs);
        end
        if o.band(2) > nyq
            warning('process_emg:bandClipped', ...
                    'High cut %g Hz exceeds Nyquist (%g Hz); using %g Hz.', ...
                    o.band(2), nyq, hi);
        end
        [b, a] = butter(o.order, [lo hi] / nyq, 'bandpass');
        y = local_filtfilt(b, a, y);
    end
    out.filtered = y;

    % --- Notch -------------------------------------------------------------
    if ~isempty(o.notch) && o.notch > 0 && o.notch < nyq
        w0 = o.notch / nyq;
        bw = w0 / o.notch_q;
        [b, a] = local_notch(w0, bw);
        y = local_filtfilt(b, a, y);
        out.notched = y;
    end
    out.filtered = y;

    % --- Rectify -----------------------------------------------------------
    r = abs(y);
    out.rectified = r;

    % --- Linear envelope ---------------------------------------------------
    if ~isempty(o.envelope) && o.envelope > 0 && o.envelope < nyq
        [b, a] = butter(2, o.envelope / nyq, 'low');
        out.envelope = local_filtfilt(b, a, r);
        out.envelope = max(out.envelope, 0);   % a low-pass can dip below zero
    else
        out.envelope = r;
    end

    % --- RMS envelope ------------------------------------------------------
    w = max(1, round(o.rms_window * fs / 1000));
    out.rms = sqrt(local_movmean(y.^2, w));

    % --- MVC normalisation --------------------------------------------------
    if ~isempty(o.mvc) && o.mvc > 0
        out.mvc_percent = 100 * out.envelope / o.mvc;
    end

    out.warnings = local_warn(out.quality);
end


% =========================================================================
function q = local_quality(x, fs, notch_hz)

    n  = numel(x);
    lo = min(x); hi = max(x);
    rng_x = hi - lo;

    q.flat = rng_x < eps || std(x) < eps;

    % A disconnected sensor rails at the amplifier limits. Count samples
    % within 1% of either extreme.
    if rng_x > 0
        tol  = 0.01 * rng_x;
        at_rail = sum(x >= hi - tol | x <= lo + tol);
        q.frac_at_rail = at_rail / n;
    else
        q.frac_at_rail = 1;
    end
    q.saturated = q.frac_at_rail > 0.20;

    q.range = rng_x;
    q.std   = std(x);

    % Crude SNR: loudest tenth of the envelope over the quietest tenth.
    e = abs(x - median(x));
    w = max(1, round(0.05 * fs));
    e = local_movmean(e, w);
    es = sort(e);
    baseline = median(es(1:max(1, round(0.1*n))));
    peak     = median(es(max(1, round(0.9*n)):end));
    if baseline > 0
        q.snr_estimate = peak / baseline;
    else
        q.snr_estimate = Inf;
    end

    % Mains contamination: power at the mains line over its neighbourhood.
    q.mains_ratio = NaN;
    f0 = notch_hz;
    if isempty(f0) || f0 <= 0
        f0 = 60;    % check the common case even when no notch was requested
    end
    if f0 < fs/2 && n >= 4
        nfft = 2^nextpow2(min(n, round(4*fs)));
        seg  = x(1:min(n, nfft));
        seg  = seg - mean(seg);
        P    = abs(fft(seg, nfft)).^2;
        fax  = (0:nfft-1) * fs / nfft;
        band = @(a, b) mean(P(fax >= a & fax < b));
        at   = band(f0 - 1, f0 + 1);
        near = band(f0 - 10, f0 - 2) + band(f0 + 2, f0 + 10);
        if near > 0
            q.mains_ratio = at / (near / 2);
        end
    end
end


function w = local_warn(q)
    w = {};
    if q.flat
        w{end+1} = 'Channel is flat - nothing is connected, or the sensor is off.';
    end
    if q.saturated
        w{end+1} = sprintf(['Channel is railed: %.0f%% of samples sit at the ', ...
            'extremes. A disconnected sensor floats to the supply limits and ', ...
            'looks like a large signal. Verify the electrode is attached.'], ...
            100 * q.frac_at_rail);
    end
    if ~q.flat && ~q.saturated && q.snr_estimate < 2
        w{end+1} = sprintf(['Low signal-to-noise (%.1fx over baseline). The ', ...
            'channel may be picking up noise rather than muscle activity.'], ...
            q.snr_estimate);
    end
    if ~isnan(q.mains_ratio) && q.mains_ratio > 10
        w{end+1} = sprintf(['Strong mains component (%.0fx its neighbours). ', ...
            'Check the ground electrode, or enable the ''notch'' option.'], ...
            q.mains_ratio);
    end
end


% =========================================================================
function [b, a] = local_notch(w0, bw)
% Second-order IIR notch, so the Signal Processing Toolbox iirnotch is not
% required.
    q  = w0 / bw;
    wo = w0 * pi;
    alpha = sin(wo) / (2 * q);
    b = [1, -2*cos(wo), 1];
    a = [1 + alpha, -2*cos(wo), 1 - alpha];
    b = b / a(1);
    a = a / a(1);
end


function y = local_filtfilt(b, a, x)
% Zero-phase filtering. Uses filtfilt when available; otherwise applies the
% filter forwards then backwards by hand, which is the same operation.
    if exist('filtfilt', 'file') == 2 || exist('filtfilt', 'builtin') == 5
        y = filtfilt(b, a, x);
        return;
    end
    npad = min(3 * max(numel(a), numel(b)), floor(numel(x)/2));
    if npad > 0
        head = 2*x(1)   - x(npad+1:-1:2);
        tail = 2*x(end) - x(end-1:-1:end-npad);
        xp = [head; x; tail];
    else
        xp = x;
    end
    y = filter(b, a, xp);
    y = flipud(filter(b, a, flipud(y)));
    if npad > 0
        y = y(npad+1:end-npad);
    end
end


function y = local_movmean(x, w)
% Centred moving average, edge-safe, without requiring movmean.
    if exist('movmean', 'file') == 2 || exist('movmean', 'builtin') == 5
        y = movmean(x, w);
        return;
    end
    n = numel(x);
    c = [0; cumsum(x(:))];
    half = floor(w/2);
    y = zeros(n, 1);
    for i = 1:n
        a = max(1, i - half);
        b = min(n, i + half);
        y(i) = (c(b+1) - c(a)) / (b - a + 1);
    end
end

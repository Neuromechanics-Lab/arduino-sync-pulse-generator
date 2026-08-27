function edges = detect_edges(signal, fs, varargin)
% DETECT_EDGES Find square-wave transition times, to sub-sample precision.
%
%   edges = detect_edges(x, fs)
%   edges = detect_edges(x, fs, 'mode', 'rectified')
%
%   Two acquisition paths need two detectors:
%
%   'level' (default) - the square wave recorded directly, e.g. straight into
%       a lock box or analog card. The signal holds its level between
%       transitions, so a Schmitt trigger with hysteresis finds the state
%       changes, and the exact crossing time comes from linear interpolation
%       across the mid-level threshold.
%
%   'rectified' - the square wave passed through an EMG amplifier. The
%       amplifier's high-pass removes the DC level, so a step becomes a
%       transient spike: a rising edge produces a positive spike and a
%       falling edge a negative one. The detector therefore searches the
%       SIGNED signal for positive and negative peaks separately, which is
%       what makes each detection carry a known polarity. Peak times are
%       located by 'locate' below - by default on the rising flank, which
%       keeps the timing bias independent of the amplifier's response.
%
%       Detecting on the signed signal rather than a rectified copy is the
%       whole point: rectifying first discards the sign, and without the sign
%       a rising edge can be matched to a falling one. See EDGE_DELAY.
%
%   Name-Value:
%       'mode'        - 'level' | 'rectified' | 'auto'  (default 'auto')
%       'hysteresis'  - Schmitt fractions [low high] of range (default [0.3 0.7])
%       'threshold'   - rectified: peak threshold in MAD units (default 8)
%       'refractory'  - rectified: minimum ms between peaks of one polarity
%                       (default 30). Suppresses ringing after a transition
%                       being counted as a second edge. Must be shorter than
%                       the shortest pulse in the pattern.
%       'min_pulse'   - level: minimum ms a level must hold (default 5)
%       'locate'      - rectified: which feature of the spike marks the
%                       transition, 'onset' (default) or 'peak'.
%
%                       This is not cosmetic. The spike PEAK lags the true
%                       transition by the amplifier's rise time, so its bias
%                       depends on the amplifier: measured against synthetic
%                       signals of known delay it ran +1.3 to +1.7 ms late,
%                       varying with the time constant. The ONSET is timed on
%                       the rising flank and its bias does NOT depend on the
%                       amplifier (+0.45 ms at the default fraction, constant
%                       across time constants from 1 to 20 ms). A fixed bias
%                       cancels out of a comparison between two channels
%                       recorded through the same hardware; a varying one
%                       does not. Onset is therefore the default.
%
%                       The cost is noise: low on the flank the signal is
%                       still small, so the spread is wider than the peak's.
%                       Raise 'onset_fraction' to trade bias back for
%                       precision, and report which you used.
%       'onset_fraction' - Height, as a fraction of each spike's own peak, at
%                       which the flank is timed (default 0.25).
%       'onset_floor' - Absolute floor for that level, in MAD units
%                       (default 2), so a tiny spike cannot be timed inside
%                       the noise.
%
%   Output struct:
%       .time      - Column vector of edge times in seconds
%       .polarity  - +1 rising, -1 falling, matching .time
%       .amplitude - Peak height (rectified) or step size (level)
%       .mode      - Detector actually used
%       .fs        - Sample rate
%       .n_rising / .n_falling
%       .noise     - Robust noise estimate (MAD-based) of the input
%
%   See also EDGE_DELAY, LOAD_C3D_ANALOG.

    p = inputParser;
    addParameter(p, 'mode',       'auto');
    addParameter(p, 'hysteresis', [0.3 0.7]);
    addParameter(p, 'threshold',  8);
    addParameter(p, 'refractory', 30);
    addParameter(p, 'min_pulse',  5);
    addParameter(p, 'locate',         'onset');
    addParameter(p, 'onset_fraction', 0.25);
    addParameter(p, 'onset_floor',    2);
    parse(p, varargin{:});
    o = p.Results;

    x = double(signal(:));
    if numel(x) < 3
        error('detect_edges:tooShort', 'Signal needs at least 3 samples.');
    end
    if ~isscalar(fs) || fs <= 0
        error('detect_edges:badRate', 'fs must be a positive scalar.');
    end

    noise = local_mad(x);

    mode = lower(o.mode);
    if strcmp(mode, 'auto')
        mode = local_classify(x, noise);
    end

    switch mode
        case 'level'
            edges = local_level_edges(x, fs, o);
        case 'rectified'
            edges = local_rectified_edges(x, fs, o, noise);
        otherwise
            error('detect_edges:badMode', ...
                  'mode must be ''level'', ''rectified'', or ''auto''.');
    end

    edges.mode      = mode;
    edges.fs        = fs;
    edges.noise     = noise;
    edges.n_rising  = sum(edges.polarity > 0);
    edges.n_falling = sum(edges.polarity < 0);
end


% =========================================================================
function mode = local_classify(x, noise)
% A directly recorded square wave spends nearly all its time at one of two
% levels, so a histogram is strongly bimodal and the middle is empty. A
% differentiated (EMG-passed) copy sits near zero and spikes.

    rng_x = max(x) - min(x);
    if rng_x <= 0 || noise <= 0
        mode = 'level';
        return;
    end

    lo = min(x); hi = max(x);
    mid_band = x > lo + 0.35*rng_x & x < lo + 0.65*rng_x;
    frac_mid = sum(mid_band) / numel(x);

    % Directly recorded: under ~10% of samples in the middle third.
    if frac_mid < 0.10
        mode = 'level';
    else
        mode = 'rectified';
    end
end


% =========================================================================
function edges = local_level_edges(x, fs, o)
% Schmitt trigger with linear-interpolation refinement of the mid crossing.

    lo = min(x); hi = max(x); rng_x = hi - lo;
    if rng_x <= 0
        edges = local_empty();
        return;
    end

    frac = sort(o.hysteresis(:))';
    thr_lo = lo + frac(1) * rng_x;
    thr_hi = lo + frac(2) * rng_x;
    mid    = (hi + lo) / 2;

    min_gap = max(1, round(o.min_pulse * fs / 1000));

    n = numel(x);
    state = x(1) > thr_hi;      % true = currently high
    t_list = zeros(n, 1);
    p_list = zeros(n, 1);
    a_list = zeros(n, 1);
    k = 0;
    last_idx = -inf;

    for i = 2:n
        going_up   = ~state && x(i) > thr_hi;
        going_down =  state && x(i) < thr_lo;
        if ~(going_up || going_down)
            continue;
        end
        state = going_up;

        % Walk back to the sample just before the mid-level crossing.
        j = i;
        while j > 1 && ((going_up && x(j) > mid) || (~going_up && x(j) < mid))
            j = j - 1;
        end

        % Linear interpolation between j and j+1 for the fractional crossing.
        if j < n
            y0 = x(j); y1 = x(j+1);
            if y1 ~= y0
                frac_s = (mid - y0) / (y1 - y0);
                frac_s = min(max(frac_s, 0), 1);
            else
                frac_s = 0;
            end
            t_cross = (j - 1 + frac_s) / fs;
        else
            t_cross = (j - 1) / fs;
        end

        if (j - last_idx) < min_gap
            continue;   % too soon after the previous edge; treat as bounce
        end
        last_idx = j;

        k = k + 1;
        t_list(k) = t_cross;
        p_list(k) = 1 - 2*(~going_up);   % +1 up, -1 down
        a_list(k) = rng_x;
    end

    edges.time      = t_list(1:k);
    edges.polarity  = p_list(1:k);
    edges.amplitude = a_list(1:k);
end


% =========================================================================
function edges = local_rectified_edges(x, fs, o, noise)
% Signed peak detection: positive peaks are rising edges, negative peaks are
% falling edges. Each polarity is searched independently on the signed
% signal so the detection carries its polarity with it.

    if noise <= 0
        edges = local_empty();
        return;
    end

    xc  = x - median(x);
    thr = o.threshold * noise;

    onset_floor = o.onset_floor * noise;
    [t_pos, a_pos] = local_signed_peaks(xc,  1, thr, fs, o.refractory, ...
                                        o.locate, o.onset_fraction, onset_floor);
    [t_neg, a_neg] = local_signed_peaks(xc, -1, thr, fs, o.refractory, ...
                                        o.locate, o.onset_fraction, onset_floor);

    t = [t_pos(:);            t_neg(:)];
    p = [ones(numel(t_pos),1); -ones(numel(t_neg),1)];
    a = [a_pos(:);            a_neg(:)];

    [t, ord] = sort(t);
    edges.time      = t;
    edges.polarity  = p(ord);
    edges.amplitude = a(ord);
end


function [times, amps] = local_signed_peaks(x, sgn, thr, fs, refractory_ms, ...
                                            locate, onset_fraction, onset_floor)
% Peaks of one polarity, enforced apart by a refractory period. When two
% candidates fall inside the refractory window the LARGER wins, so ringing
% after a real transition cannot displace the transition itself.

    s = x * sgn;
    n = numel(s);
    above = s > thr;

    % Collect one candidate per supra-threshold run.
    cand_idx = zeros(n, 1);
    cand_val = zeros(n, 1);
    c = 0;
    i = 1;
    while i <= n
        if above(i)
            j = i;
            while j <= n && above(j)
                j = j + 1;
            end
            [v, rel] = max(s(i:j-1));
            c = c + 1;
            cand_idx(c) = i + rel - 1;
            cand_val(c) = v;
            i = j;
        else
            i = i + 1;
        end
    end
    cand_idx = cand_idx(1:c);
    cand_val = cand_val(1:c);

    if c == 0
        times = []; amps = [];
        return;
    end

    % Greedy largest-first selection under the refractory constraint.
    refrac = max(1, round(refractory_ms * fs / 1000));
    [~, order] = sort(cand_val, 'descend');
    keep = false(c, 1);
    kept_idx = zeros(c, 1);
    n_kept = 0;
    for q = 1:c
        ci = cand_idx(order(q));
        ok = true;
        for r = 1:n_kept
            if abs(ci - kept_idx(r)) < refrac
                ok = false;
                break;
            end
        end
        if ok
            n_kept = n_kept + 1;
            kept_idx(n_kept) = ci;
            keep(order(q)) = true;
        end
    end

    sel_idx = sort(cand_idx(keep));
    times = zeros(numel(sel_idx), 1);
    amps  = zeros(numel(sel_idx), 1);

    for q = 1:numel(sel_idx)
        k = sel_idx(q);
        amps(q) = s(k);

        if strcmpi(locate, 'onset')
            % Walk back from the peak to where the rising flank crosses a
            % level set as a FRACTION OF THIS SPIKE'S OWN AMPLITUDE, then
            % interpolate that crossing.
            %
            % An absolute threshold a few MADs up sits at the very foot of
            % the flank, where the signal is nearly flat: which sample first
            % exceeds it then depends on noise, and the interpolated time
            % snaps to one sample or the next. On real data that split a
            % single population into two modes about one sample apart. A
            % fractional level sits on the steep part of the flank, where an
            % amplitude error moves the crossing time very little, and it
            % scales automatically with spike size.
            %
            % The level is a fixed fraction of the rise, so it lands a
            % constant delay after the true transition rather than on it -
            % but that delay is the same for every edge of a given shape, so
            % it cancels out of a delay measurement.
            level = max(onset_floor, onset_fraction * s(k));
            j = k;
            while j > 1 && s(j) > level
                j = j - 1;
            end
            if j < k
                y0 = s(j); y1 = s(j+1);
                if y1 ~= y0
                    frac = (level - y0) / (y1 - y0);
                    frac = min(max(frac, 0), 1);
                else
                    frac = 0;
                end
                times(q) = (j - 1 + frac) / fs;
            else
                times(q) = (j - 1) / fs;
            end
            continue;
        end

        % locate == 'peak': parabolic interpolation through (k-1, k, k+1).
        if k > 1 && k < n
            y0 = s(k-1); y1 = s(k); y2 = s(k+1);
            den = y0 - 2*y1 + y2;
            if den ~= 0
                delta = 0.5 * (y0 - y2) / den;
                delta = min(max(delta, -1), 1);
            else
                delta = 0;
            end
        else
            delta = 0;
        end
        times(q) = (k - 1 + delta) / fs;
    end
end


% =========================================================================
function e = local_empty()
    e.time = []; e.polarity = []; e.amplitude = [];
end


function m = local_mad(x)
% Robust noise estimate: MAD scaled to be consistent with the standard
% deviation for Gaussian data.
    m = 1.4826 * median(abs(x - median(x)));
end

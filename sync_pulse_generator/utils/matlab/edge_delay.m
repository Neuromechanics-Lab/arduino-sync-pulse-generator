function result = edge_delay(edges_ref, edges_test, varargin)
% EDGE_DELAY Delay between two recordings of the same square wave, from edges.
%
%   result = edge_delay(edges_ref, edges_test)
%   result = edge_delay(e_direct, e_wireless, 'max_delay', 60)
%
%   Takes two DETECT_EDGES outputs of the SAME square wave captured on two
%   paths, pairs their edges, and reports the delay between them. A positive
%   delay means the test signal arrives AFTER the reference.
%
%   Matching rules, and why each one is there:
%
%   1. Polarity is respected. A rising edge is only ever matched to a rising
%      edge. Mixing polarities inflates the spread, because a rising and a
%      falling transition are different events separated by a pulse width.
%
%   2. Matching is causal. A candidate must fall within [min_delay max_delay]
%      of the reference edge. The test signal cannot physically precede the
%      reference, so a negative-delay pairing is a detection artefact and is
%      excluded rather than averaged in.
%
%   3. Ties go to the largest peak. When several candidates sit inside the
%      window, the strongest is taken. Spurious peaks are small; the real
%      transition is not.
%
%   Together these turn a nearest-neighbour match into one that does not
%   silently pair an edge with noise.
%
%   Name-Value:
%       'min_delay'  - Earliest allowed delay in ms (default -2, a small
%                      negative tolerance for sub-sample jitter at zero delay)
%       'max_delay'  - Latest allowed delay in ms (default 100)
%       'outlier_mad'- Flag matches beyond this many MADs (default 5, 0=off)
%
%   Output struct:
%       .delay_ms        - Median delay (the headline number; robust)
%       .delay_mean_ms   - Mean delay over accepted matches
%       .delay_std_ms    - Standard deviation
%       .delay_iqr_ms    - Interquartile range
%       .ci95_ms         - Half-width of the 95% CI on the mean
%       .n_matched       - Matches accepted
%       .n_reference     - Reference edges available
%       .match_rate      - n_matched / n_reference
%       .rising / .falling - Per-polarity substructs (median, std, n).
%                          Close agreement between them is a strong check
%                          that the pairing is correct.
%       .drift_ms_per_s  - Slope of delay against trial time
%       .drift_total_ms  - Slope extrapolated over the whole trial
%       .times           - Reference edge time of each match (s)
%       .deltas_ms       - Per-match delay, aligned with .times
%       .polarities      - Per-match polarity
%       .n_outliers      - Matches beyond outlier_mad
%       .outlier_idx     - Their indices into .deltas_ms
%       .warnings        - Cell array of quality notes, empty when clean
%
%   See also DETECT_EDGES, SHIFT_TIMESTAMPS, PLOT_SYNC_CHECK.

    p = inputParser;
    addParameter(p, 'min_delay',   -2);
    addParameter(p, 'max_delay',   100);
    addParameter(p, 'outlier_mad', 5);
    parse(p, varargin{:});
    o = p.Results;

    if o.min_delay >= o.max_delay
        error('edge_delay:badWindow', 'min_delay must be below max_delay.');
    end

    t_ref = edges_ref.time(:);
    p_ref = edges_ref.polarity(:);
    t_tst = edges_test.time(:);
    p_tst = edges_test.polarity(:);

    if isfield(edges_test, 'amplitude') && ~isempty(edges_test.amplitude)
        a_tst = abs(edges_test.amplitude(:));
    else
        a_tst = ones(size(t_tst));
    end

    if isempty(t_ref) || isempty(t_tst)
        error('edge_delay:noEdges', ...
              'Both inputs need edges (reference %d, test %d).', ...
              numel(t_ref), numel(t_tst));
    end

    [tr, dr, pr] = local_match(t_ref, p_ref, t_tst, p_tst, a_tst,  1, o);
    [tf, df, pf] = local_match(t_ref, p_ref, t_tst, p_tst, a_tst, -1, o);

    times  = [tr; tf];
    deltas = [dr; df];
    pols   = [pr; pf];
    [times, ord] = sort(times);
    deltas = deltas(ord);
    pols   = pols(ord);

    if isempty(deltas)
        error('edge_delay:noMatches', ...
              ['No edges paired inside [%g %g] ms. Check that both channels ', ...
               'carry the same square wave, and widen max_delay if the true ', ...
               'delay could exceed it.'], o.min_delay, o.max_delay);
    end

    result.delay_ms      = median(deltas);
    result.delay_mean_ms = mean(deltas);
    result.delay_std_ms  = std(deltas);
    result.delay_iqr_ms  = local_iqr(deltas);
    result.ci95_ms       = 1.96 * std(deltas) / sqrt(numel(deltas));
    result.n_matched     = numel(deltas);
    result.n_reference   = numel(t_ref);
    result.match_rate    = numel(deltas) / numel(t_ref);

    result.rising  = local_stats(dr);
    result.falling = local_stats(df);

    % Drift: a real clock mismatch shows as a consistent slope, whereas a
    % fixed hardware latency has none.
    if numel(deltas) >= 3 && range(times) > 0
        A  = [times, ones(numel(times), 1)];
        cf = A \ deltas;
        result.drift_ms_per_s = cf(1);
        result.drift_total_ms = cf(1) * range(times);
        result.intercept_ms   = cf(2);
    else
        result.drift_ms_per_s = 0;
        result.drift_total_ms = 0;
        result.intercept_ms   = result.delay_ms;
    end

    result.times      = times;
    result.deltas_ms  = deltas;
    result.polarities = pols;

    % Outliers are reported, not removed: the causal window already excludes
    % impossible pairings, so anything left is worth a human look.
    if o.outlier_mad > 0
        m   = median(deltas);
        mad = 1.4826 * median(abs(deltas - m));
        if mad > 0
            bad = abs(deltas - m) > o.outlier_mad * mad;
        else
            bad = false(size(deltas));
        end
        result.n_outliers  = sum(bad);
        result.outlier_idx = find(bad);
    else
        result.n_outliers  = 0;
        result.outlier_idx = [];
    end

    result.warnings = local_quality(result, edges_ref, edges_test);
end


% =========================================================================
function [times, deltas, pols] = local_match(t_ref, p_ref, t_tst, p_tst, a_tst, pol, o)
% Pair every reference edge of one polarity with the strongest test edge of
% the same polarity inside the causal window.

    ref_sel = t_ref(p_ref == pol);
    tst_sel = t_tst(p_tst == pol);
    amp_sel = a_tst(p_tst == pol);

    times  = zeros(numel(ref_sel), 1);
    deltas = zeros(numel(ref_sel), 1);
    pols   = zeros(numel(ref_sel), 1);
    k = 0;

    if isempty(tst_sel)
        times = []; deltas = []; pols = [];
        return;
    end

    for i = 1:numel(ref_sel)
        d_ms = (tst_sel - ref_sel(i)) * 1000;
        in   = d_ms >= o.min_delay & d_ms <= o.max_delay;
        if ~any(in)
            continue;
        end
        idx = find(in);
        [~, best] = max(amp_sel(idx));
        k = k + 1;
        times(k)  = ref_sel(i);
        deltas(k) = d_ms(idx(best));
        pols(k)   = pol;
    end

    times  = times(1:k);
    deltas = deltas(1:k);
    pols   = pols(1:k);
end


function s = local_stats(d)
    if isempty(d)
        s = struct('median_ms', NaN, 'mean_ms', NaN, 'std_ms', NaN, 'n', 0);
    else
        s = struct('median_ms', median(d), 'mean_ms', mean(d), ...
                   'std_ms', std(d), 'n', numel(d));
    end
end


function v = local_iqr(x)
    if isempty(x)
        v = NaN;
    else
        q = prctile_local(x, [25 75]);
        v = q(2) - q(1);
    end
end


function q = prctile_local(x, pcts)
% Percentile without the Statistics Toolbox (linear interpolation).
    x = sort(x(:));
    n = numel(x);
    q = zeros(size(pcts));
    for i = 1:numel(pcts)
        if n == 1
            q(i) = x(1);
            continue;
        end
        pos = pcts(i)/100 * (n - 1) + 1;
        lo  = floor(pos); hi = ceil(pos);
        if lo == hi
            q(i) = x(lo);
        else
            q(i) = x(lo) + (pos - lo) * (x(hi) - x(lo));
        end
    end
end


function w = local_quality(r, e_ref, e_tst)
% Turn the numbers into plain statements about whether to trust the result.

    w = {};

    if r.match_rate < 0.9
        w{end+1} = sprintf(['Only %.0f%% of reference edges matched (%d of %d). ', ...
            'Check the detector settings on the test channel.'], ...
            100*r.match_rate, r.n_matched, r.n_reference);
    end

    if r.n_outliers > 0
        w{end+1} = sprintf(['%d matched edges are more than 5 MADs from the ', ...
            'median. Inspect them before trusting the mean.'], r.n_outliers);
    end

    if r.delay_std_ms > 2
        w{end+1} = sprintf(['Delay spread is %.2f ms (std). A fixed hardware ', ...
            'latency should be well under 1 ms; this suggests detection ', ...
            'problems or a genuinely variable link.'], r.delay_std_ms);
    end

    if ~isnan(r.rising.median_ms) && ~isnan(r.falling.median_ms)
        asym = abs(r.rising.median_ms - r.falling.median_ms);
        if asym > 1
            w{end+1} = sprintf(['Rising and falling edges disagree by %.2f ms ', ...
                '(%.3f vs %.3f). Asymmetry this large usually means the edge ', ...
                'detector is mis-locating one polarity.'], ...
                asym, r.rising.median_ms, r.falling.median_ms);
        end
    end

    if abs(r.drift_total_ms) > 1
        w{end+1} = sprintf(['Delay drifts %.2f ms across the trial. The two ', ...
            'devices may be running on independent clocks; a single offset ', ...
            'will not align them properly.'], r.drift_total_ms);
    end

    % Only compare edge counts when BOTH channels used the same detector.
    %
    % A level detector reports one edge per transition. A rectified detector
    % reports a positive AND a negative peak at every transition, because the
    % amplifier's response overshoots on the way back: a step up gives a
    % positive spike followed by a negative one. So a correctly detected
    % rectified channel legitimately carries about twice the reference's edge
    % count in EVERY polarity, and flagging that ratio calls a good detection
    % bad.
    %
    % Whether the pairing actually worked is told by the match rate and the
    % rising/falling agreement, both already checked above.
    n_ref = numel(e_ref.time);
    n_tst = numel(e_tst.time);
    if strcmp(e_ref.mode, e_tst.mode) && n_ref > 0 && n_tst > 1.5 * n_ref
        w{end+1} = sprintf(['Test channel yielded %d edges against %d in the ', ...
            'reference, using the same detector. Raise ''threshold'' or ', ...
            '''refractory'' in detect_edges if spurious peaks are being ', ...
            'detected.'], n_tst, n_ref);
    end
end

function fit = align_lock(src, tmpl, tol_s)
% ALIGN_LOCK Place one recording on the template timeline.
%
%   fit = align_lock(src, tmpl, tol_s)
%
%   Order of preference:
%     1. Decode the binary timecode frames. Each states its elapsed second
%        outright and is checksum verified, so it anchors its own window with
%        no search and no ambiguity — and it identifies the run.
%     2. Failing that, fingerprint the pseudo-random interval gaps. A device
%        that low-passes the signal may smear the 5/15/25 ms frame intervals
%        past decoding while its 50-500 ms pseudo-random edges stay clean.
%
%   Either way the anchors are then read directly: offset and clock rate come
%   from a fit through them, and a lost-count step shows as a jump that
%   persists.
%
%   See also ALIGN_SOURCES, ALIGN_FRAMES, ALIGN_APPLY.

    if nargin < 3 || isempty(tol_s), tol_s = 0.006; end

    K = tmpl.k;
    MIN_VOTES = 3;
    ANCHOR_WIN = 60;      % pseudo-random intervals per local lock
    ANCHOR_STRIDE = 30;
    MIN_CONF = 0.85;
    STEP_S = 0.010;

    fit = struct('name', src.name, 'ok', false, 'offset_s', NaN, 'rate', NaN, ...
        'drift_ppm', NaN, 'n_edges', numel(src.edges), 'n_matched', 0, ...
        'match_rate', 0, 'rms_ms', NaN, 'confidence', 0, 'run_id', [], ...
        'source_of_lock', '', 'segments', [], 'drops', zeros(0,2), ...
        'frame_gaps', zeros(0,3), 'anchors', zeros(0,2), 'nonlinear', false, ...
        'note', '');

    e = src.edges(:);
    if numel(e) < K + 1
        fit.note = sprintf('only %d edges; need at least %d', numel(e), K+1);
        return;
    end

    stream = 'both';
    if ~isempty(src.polarity)
        if all(src.polarity > 0),      stream = 'rising';
        elseif all(src.polarity < 0),  stream = 'falling';
        end
    end
    sub = tmpl.(stream);

    % --- 1. timecode frames -------------------------------------------------
    [frames, run_id] = align_frames(src);
    fit.run_id = run_id;

    A = zeros(0,3);
    if numel(frames) >= 2
        A = [ [frames.t_rec]', double([frames.elapsed_s])', ones(numel(frames),1) ];
        fit.source_of_lock = 'timecode';

        % Frames arrive on a known cadence, so a gap in the sequence says
        % both that data is missing and which window it is missing from —
        % a much tighter bound on where to cut than a fitted residual gives.
        interval = NaN;
        if numel(frames) >= 2
            d = diff(double([frames.elapsed_s]));
            interval = median(d(d > 0));
        end
        if isfinite(interval) && interval > 0
            for k = 2:numel(frames)
                de = double(frames(k).elapsed_s) - double(frames(k-1).elapsed_s);
                if de > 1.5 * interval
                    fit.frame_gaps(end+1,:) = [frames(k-1).t_rec, ...
                        frames(k).t_rec, floor(de/interval) - 1]; %#ok<AGROW>
                end
            end
        end
    end

    % --- 2. fingerprint fallback --------------------------------------------
    if size(A,1) < 2
        [piv, ppos] = local_pr(e, tmpl.pr_min);
        if numel(piv) < K
            fit.note = sprintf(['only %d pseudo-random intervals (>= %.0f ms); ', ...
                'the recording may be too short, or all its edges fall inside ', ...
                'timecode frames'], numel(piv), tmpl.pr_min*1000);
            return;
        end
        w = 1;
        while w + ANCHOR_WIN - 1 <= numel(piv)
            sl = w : w+ANCHOR_WIN-1;
            [sh, sc, tot] = local_vote(piv(sl), ppos(sl), sub, tol_s, K);
            if ~isempty(sh) && sc >= MIN_VOTES && tot > 0
                i = ppos(w); j = i + sh;
                if i >= 1 && i <= numel(e) && j >= 1 && j <= numel(sub.edges)
                    A(end+1,:) = [e(i), sub.edges(j), sc/tot]; %#ok<AGROW>
                end
            end
            w = w + ANCHOR_STRIDE;
        end
        if isempty(A)
            [sh, sc, tot] = local_vote(piv, ppos, sub, tol_s, K);
            if ~isempty(sh) && sc >= MIN_VOTES
                i = ppos(1); j = i + sh;
                if j >= 1 && j <= numel(sub.edges)
                    A(end+1,:) = [e(i), sub.edges(j), sc/max(tot,1)];
                end
            end
        end
        fit.source_of_lock = 'fingerprint';
    end

    if isempty(A)
        fit.note = ['could not lock to the template. Check that the seed and ', ...
                    'timing config match the firmware that produced this ', ...
                    'recording, and that the sync channel is the right one.'];
        return;
    end

    fit.confidence = median(A(:,3));
    good = A(A(:,3) >= MIN_CONF, :);
    if isempty(good)
        good = A(A(:,3) >= max(0.5, max(A(:,3))*0.9), :);
    end
    if isempty(good)
        fit.note = 'locked only weakly; no window reached usable confidence';
        return;
    end

    tl = good(:,1); tg = good(:,2);
    fit.anchors = [tl, tg];

    % Does the clock wander? A straight-line clock leaves residuals at the
    % anchor noise floor; a wandering one curves away from it.
    if numel(tl) >= 4
        c = polyfit(tl, tg, 1);
        r = tg - (c(1)*tl + c(2));
        fit.nonlinear = max(abs(r)) > 0.004;
    end

    % Lost-count steps: the offset jumps and stays jumped.
    offs = tg - tl;
    segs = zeros(0,4); drops = zeros(0,2);
    if numel(tl) >= 2
        jumps = find(abs(diff(offs)) > STEP_S);
        bounds = [1; jumps(:)+1; numel(tl)+1];
        for b = 1:numel(bounds)-1
            a1 = bounds(b); a2 = bounds(b+1)-1;
            if a2 < a1, continue; end
            if a2 - a1 >= 1
                c = polyfit(tl(a1:a2), tg(a1:a2), 1);
                rate = c(1);
            else
                rate = 1;
            end
            offset = median(tg(a1:a2) - rate*tl(a1:a2));
            t_end = tl(a2);
            if b == numel(bounds)-1, t_end = e(end); end
            segs(end+1,:) = [tl(a1), t_end, offset, rate]; %#ok<AGROW>
        end
        for k = 1:numel(jumps)
            if k+1 <= size(segs,1)
                drops(end+1,:) = [tl(jumps(k)+1), ...
                                  (segs(k+1,3)-segs(k,3))*1000]; %#ok<AGROW>
            end
        end
    end
    if isempty(segs)
        segs = [e(1), e(end), median(offs), 1];
    end

    if size(segs,1) > 1, fit.segments = segs; else, fit.segments = []; end
    fit.offset_s  = segs(1,3);
    fit.rate      = segs(1,4);
    fit.drift_ppm = (fit.rate - 1) * 1e6;
    fit.drops     = drops;

    % Final pairing against the fitted map, for match rate and residuals.
    pred = align_apply(fit, e);
    [ps, pt] = local_pair(e, pred, sub.edges, tol_s);
    fit.n_matched  = numel(ps);
    fit.match_rate = numel(ps) / max(1, numel(e));
    if ~isempty(ps)
        resid = pt - align_apply(fit, ps);
        fit.rms_ms = sqrt(mean(resid.^2)) * 1000;
    end
    fit.ok = true;
end


% =========================================================================
function [iv, pos] = local_pr(edges, pr_min)
% Pseudo-random intervals only. Frame internals are short and repetitive and
% would swamp the fingerprint.
    if numel(edges) < 2
        iv = []; pos = []; return;
    end
    d = diff(edges(:));
    keep = d >= pr_min;
    iv = d(keep);
    pos = find(keep);
end


function [shift, score, total] = local_vote(piv, ppos, sub, tol_s, K)
% Coarse alignment by voting across many short interval windows. The true
% offset is proposed by every clean window; a window spanning a dropped edge
% proposes noise, so the plurality tolerates a substantial bad fraction.
    shift = []; score = 0; total = 0;
    n = numel(sub.iv);
    if n < K || numel(piv) < K, return; end

    nwin = n - K + 1;
    W = zeros(nwin, K);
    for k = 1:K
        W(:,k) = sub.iv(k : k + nwin - 1);
    end

    votes = containers.Map('KeyType','double','ValueType','double');
    nprobe = numel(piv) - K + 1;
    for w = 1:nprobe
        probe = piv(w:w+K-1)';
        d = max(abs(W - probe), [], 2);
        hits = find(d < tol_s);
        for h = hits'
            key = sub.pos(h) - ppos(w);
            if isKey(votes, key)
                votes(key) = votes(key) + 1;
            else
                votes(key) = 1;
            end
        end
    end

    if votes.Count == 0, return; end
    ks = cell2mat(keys(votes));
    vs = cell2mat(values(votes));
    [score, i] = max(vs);
    shift = ks(i);
    total = sum(vs);
end


function [ps, pt] = local_pair(src_edges, pred, tmpl_edges, tol_s)
% Pair each source edge with the template edge nearest its prediction.
    ps = []; pt = [];
    for i = 1:numel(src_edges)
        [d, j] = min(abs(tmpl_edges - pred(i)));
        if d <= tol_s
            ps(end+1,1) = src_edges(i); %#ok<AGROW>
            pt(end+1,1) = tmpl_edges(j); %#ok<AGROW>
        end
    end
end

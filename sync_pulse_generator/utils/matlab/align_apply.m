function g = align_apply(fit, t_local)
% ALIGN_APPLY Map a recording's own clock onto global (template) time.
%
%   g = align_apply(fit, t_local)
%
%   Uses whichever model the lock produced:
%
%     * a SLIDING window over the timecode anchors, when the anchors show
%       the clock actually changing. The window is centred so each point
%       sits between anchors on both sides rather than at a segment edge,
%       and adjacent windows overlap — so a correction blends across a cut
%       instead of stepping at it;
%     * a piecewise map, when the recorder lost count and the timeline
%       stepped;
%     * a single line otherwise, which is exact for a steady clock.
%
%   See also ALIGN_LOCK, ALIGN_SOURCES.

    t = t_local(:);

    % Sliding window over frame anchors (only when the clock wanders — on a
    % steady recorder a global line is exact and local fits would just
    % inject anchor noise).
    if fit.nonlinear && size(fit.anchors, 1) >= 4
        ta = fit.anchors(:,1); ga = fit.anchors(:,2);
        n = numel(ta);
        g = zeros(size(t));
        for i = 1:numel(t)
            k  = sum(ta <= t(i));
            lo = max(1, min(k, n - 3));
            hi = min(n, lo + 3);
            lo = max(1, hi - 3);
            if hi - lo >= 1
                c = polyfit(ta(lo:hi), ga(lo:hi), 1);
                g(i) = c(1)*t(i) + c(2);
            else
                g(i) = t(i) + (ga(lo) - ta(lo));
            end
        end
        return;
    end

    % Piecewise: a lost-count step shifts everything after it.
    if ~isempty(fit.segments)
        segs = fit.segments;
        starts = segs(:,1);
        g = zeros(size(t));
        for i = 1:numel(t)
            k = sum(starts <= t(i));
            k = max(1, min(k, size(segs,1)));
            g(i) = segs(k,3) + segs(k,4) * t(i);
        end
        return;
    end

    g = fit.offset_s + fit.rate * t;
end

function tmpl = align_template(duration_s, run_id)
% ALIGN_TEMPLATE Edge times of the intended signal, generated from code.
%
%   tmpl = align_template(duration_s, run_id)
%
%   The generator's output is fully determined by (seed, config), so the
%   waveform every device should have seen can be reproduced offline. That
%   template is what each recording is locked to.
%
%   Returns a struct with .both / .rising / .falling, each carrying:
%       .edges  transition times (s)
%       .iv     PSEUDO-RANDOM intervals only (see below)
%       .pos    index into .edges of each kept interval
%
%   Frame-internal intervals are excluded from .iv. Timecode frame pulses are
%   5/15/25 ms drawn from a tiny alphabet and are ~77% of all transitions in
%   an hour; including them makes roughly 75% of fingerprint windows match
%   somewhere else. Excluding them, a window of 4 intervals is unique across
%   a full hour. The pseudo-random minimum is 50 ms, so 45 ms separates the
%   two populations with margin.
%
%   See also ALIGN_SOURCES, GENERATE_SYNC_SIGNAL.

    if nargin < 2 || isempty(run_id), run_id = 1; end

    PR_MIN = 0.045;
    K = 4;

    [times_ms, levels] = generate_sync_signal_tc(duration_s, run_id);
    t = times_ms(:) / 1000;
    pol = double(levels(:));
    pol(pol == 0) = -1;

    tmpl.time = t;
    tmpl.polarity = pol;
    tmpl.run_id = run_id;
    tmpl.pr_min = PR_MIN;
    tmpl.k = K;

    names = {'both', 'rising', 'falling'};
    for i = 1:3
        switch names{i}
            case 'both',    sel = true(size(t));
            case 'rising',  sel = pol > 0;
            case 'falling', sel = pol < 0;
        end
        et = t(sel);
        iv = diff(et);
        keep = iv >= PR_MIN;
        s.edges = et;
        s.iv    = iv(keep);
        s.pos   = find(keep);
        tmpl.(names{i}) = s;
    end
end

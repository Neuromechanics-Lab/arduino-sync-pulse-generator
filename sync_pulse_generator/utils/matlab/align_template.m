function tmpl = align_template(duration_s, run_id, varargin)
% ALIGN_TEMPLATE Edge times of the intended signal, generated from code.
%
%   tmpl = align_template(duration_s, run_id)
%   tmpl = align_template(duration_s, [], 'variant', 'simple')
%   tmpl = align_template(duration_s, [], 'variant', 'simple', 'seed', 42)
%
%   WHICH VARIANT — get this right first, it is not a detail
%   'full' (default) is the firmware that emits timecode frames, on the finer
%   quantum. 'simple' is sync_pulse_simple.ino: the bare pseudo-random square
%   wave, 50-500 ms in 5 ms steps, no frames.
%
%   Choosing wrong does not degrade a lock, it PREVENTS one. The frame
%   variant's intervals are dominated by 5/15/25 ms frame pulses, so a simple
%   recording matches none of it — and the failure reads as corrupt data
%   rather than as a configuration mismatch. If a long clean recording will
%   not lock, check this before anything else.
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

    p = inputParser;
    p.KeepUnmatched = true;
    addParameter(p, 'variant', 'full');
    parse(p, varargin{:});
    variant = validatestring(p.Results.variant, {'full', 'simple'});

    % Pass any remaining name-value pairs (seed, min_ms, ...) to the generator.
    extra = {};
    f = fieldnames(p.Unmatched);
    for i = 1:numel(f)
        extra{end+1} = f{i};                 %#ok<AGROW>
        extra{end+1} = p.Unmatched.(f{i});   %#ok<AGROW>
    end

    switch variant
        case 'full'
            % Frame pulses are 5/15/25 ms from a tiny alphabet and make up
            % ~77%% of transitions in an hour, so they are excluded from the
            % fingerprint intervals below.
            PR_MIN = 0.045;
            [times_ms, levels] = generate_sync_signal_tc(duration_s, run_id, extra{:});
        case 'simple'
            % No frames, so every interval is pseudo-random and every one is
            % usable. The minimum pulse is 50 ms; nothing to exclude.
            PR_MIN = 0;
            [times_ms, levels] = generate_sync_edges(duration_s, extra{:});
    end

    K = 4;
    t = times_ms(:) / 1000;
    pol = double(levels(:));
    pol(pol == 0) = -1;

    tmpl.time = t;
    tmpl.polarity = pol;
    tmpl.run_id  = run_id;
    tmpl.pr_min  = PR_MIN;
    tmpl.k       = K;
    tmpl.variant = variant;

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

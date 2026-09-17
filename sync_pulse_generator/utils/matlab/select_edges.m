function sub = select_edges(edges, t0, t1, varargin)
% SELECT_EDGES Take a time window out of a DETECT_EDGES result.
%
%   sub = select_edges(edges, t0, t1)
%   sub = select_edges(edges, t0, t1, 'pad', 0.05)
%   sub = select_edges(edges, t0, t1, 'invert', true)
%
%   Returns a struct of the same shape DETECT_EDGES produces, carrying only
%   the transitions between t0 and t1. Every field is carried through, so the
%   result can be passed to EDGE_DELAY or anything else that expects a
%   detector output.
%
%   WHY THIS EXISTS
%   EDGE_DELAY pairs every reference edge it is given. Matching a short epoch
%   into a long recording therefore needs the reference narrowed first: hand
%   it ten minutes of edges against three seconds of test and almost nothing
%   pairs, which reads as "no edges paired" rather than as a windowing
%   mistake. Slicing the struct by hand loses .mode and .fs, and EDGE_DELAY's
%   quality checks then error on the missing fields.
%
%   Name-Value:
%       'pad'    - seconds of slack added either side (default 0). A little
%                  padding stops an edge that sits exactly on the boundary
%                  from being dropped by a rounding difference.
%       'invert' - flip the polarity of every edge (default false). Use it
%                  when two systems record the same wave through opposite
%                  wiring, so one reads a rising edge where the other reads a
%                  falling one. EDGE_DELAY refuses to pair across polarity —
%                  correctly, since a rising and a falling transition are
%                  different events — so an inverted channel must be declared
%                  rather than tolerated.
%
%   Example — place a 3 s trial inside a 10 min recording, then check it:
%       eeg   = detect_edges(eeg_sync, 1000);
%       trial = detect_edges(trial_sync, 1000);
%       shifted = trial; shifted.time = trial.time + t0;
%       ref = select_edges(eeg, shifted.time(1), shifted.time(end), 'pad', 0.05);
%       d   = edge_delay(ref, shifted);
%
%   See also DETECT_EDGES, EDGE_DELAY.

    p = inputParser;
    addParameter(p, 'pad',    0);
    addParameter(p, 'invert', false);
    parse(p, varargin{:});
    o = p.Results;

    assert(isstruct(edges) && isfield(edges, 'time'), ...
        'select_edges expects a detect_edges result');

    keep = edges.time >= (t0 - o.pad) & edges.time <= (t1 + o.pad);

    sub = edges;
    % Per-edge fields get sliced; everything else (mode, fs, noise) is carried
    % through untouched, which is what keeps the result a valid detector
    % output rather than a bare struct.
    for f = {'time', 'polarity', 'amplitude'}
        if isfield(edges, f{1})
            v = edges.(f{1});
            sub.(f{1}) = v(keep);
        end
    end

    if o.invert && isfield(sub, 'polarity')
        sub.polarity = -sub.polarity;
    end

    if isfield(sub, 'polarity')
        sub.n_rising  = sum(sub.polarity > 0);
        sub.n_falling = sum(sub.polarity < 0);
    end
end

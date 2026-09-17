function [t0, n_cand, hits] = template_locate(edge_t, tmpl, varargin)
% TEMPLATE_LOCATE Where a recording sits on the generator's clock.
%
%   t0 = template_locate(edge_t, tmpl)
%   [t0, n_cand] = template_locate(edge_t, tmpl, 'k', 6, 'tol_ms', 3)
%
%   Fingerprints a recording's interval pattern against a template from
%   ALIGN_TEMPLATE and returns the generator time corresponding to the
%   recording's t = 0.
%
%   Each recording locates INDEPENDENTLY. A trial does not need the continuous
%   file to place itself and vice versa, so any two recordings relate through
%   the generator without ever being compared — which is what lets recordings
%   that never overlap land on one timeline, and what makes trials either side
%   of a recording break correctly separated by real elapsed time.
%
%   INPUT
%     edge_t - transition times in seconds, the recording's own clock. Use
%              DETECT_EDGES to get these from a waveform.
%     tmpl   - an ALIGN_TEMPLATE result. Match the variant to the firmware
%              that made the recording; see ALIGN_TEMPLATE.
%
%   Name-Value:
%     'k'       intervals in the fingerprint (default 6). Longer is more
%               certain and needs more edges. A short epoch may not have them.
%     'tol_ms'  how far an interval may differ and still count (default 3).
%     'step_ms' the generator's duration quantum (default 5). Detected edges
%               are snapped to this grid first: the box only ever emits
%               multiples of it, so a measured 146 ms is really 145, and exact
%               matching finds nothing without the snap.
%
%   OUTPUT
%     t0      generator time of the recording's t = 0, NaN if not located
%     n_cand  how many template positions matched. Should be 1. More than one
%             means the fingerprint was not unique — raise 'k'.
%     hits    every matching template index, for inspection
%
%   IF IT DOES NOT LOCATE
%   Usually the template is too short. The generator may have been running for
%   hours before recording began, and a template shorter than that elapsed
%   time cannot contain the pattern. This failure reads as corrupt data and is
%   not. Check the variant too — see ALIGN_TEMPLATE.
%
%   See also ALIGN_TEMPLATE, DETECT_EDGES, ALIGN_LOCK.

    p = inputParser;
    addParameter(p, 'k',       6);
    addParameter(p, 'tol_ms',  3);
    addParameter(p, 'step_ms', 5);
    parse(p, varargin{:});
    o = p.Results;

    edge_t = edge_t(:);
    tt = tmpl.time(:)';
    tv = round(diff(tt)*1000 / o.step_ms) * o.step_ms;   % template intervals

    pat = round(diff(edge_t)*1000 / o.step_ms) * o.step_ms;
    if numel(pat) < o.k
        t0 = NaN; n_cand = 0; hits = [];
        return;
    end
    pat = pat(1:o.k)';

    hits = [];
    for j = 1:(numel(tv) - o.k)
        if all(abs(tv(j:j+o.k-1) - pat) <= o.tol_ms)
            hits(end+1) = j; %#ok<AGROW>
        end
    end

    n_cand = numel(hits);
    if isempty(hits)
        t0 = NaN;
    else
        t0 = tt(hits(1)) - edge_t(1);
    end
end

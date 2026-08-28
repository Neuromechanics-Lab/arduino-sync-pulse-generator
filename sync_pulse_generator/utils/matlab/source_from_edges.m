function src = source_from_edges(name, edge_times, polarity, varargin)
% SOURCE_FROM_EDGES A recording that reports transition TIMESTAMPS.
%
%   src = source_from_edges('eeg', times, 'rising')
%   src = source_from_edges('daq', times, 'both', 'fs', 1000, 'data', X)
%
%   The case where a device gives you events rather than a waveform. A
%   rising-only or falling-only stream aligns just as well as a full one:
%   the fingerprint is built from the gaps between the edges you did record,
%   and those gaps are still drawn from the pseudo-random sequence.
%
%   polarity: 'rising' | 'falling' | 'both' | vector of +1/-1
%
%   See also SOURCE_FROM_CONTINUOUS, ALIGN_SOURCES.

    p = inputParser;
    addParameter(p, 'fs',     []);
    addParameter(p, 'data',   []);
    addParameter(p, 'labels', {});
    addParameter(p, 'time',   []);
    parse(p, varargin{:});
    o = p.Results;

    if nargin < 3 || isempty(polarity), polarity = 'both'; end
    t = sort(edge_times(:));

    if ischar(polarity) || isstring(polarity)
        switch lower(string(polarity))
            case "rising",  pol = ones(numel(t),1);
            case "falling", pol = -ones(numel(t),1);
            case "both",    pol = [];
            otherwise
                error('source_from_edges:badPolarity', ...
                      'polarity must be ''rising'', ''falling'', ''both'', or a vector.');
        end
    else
        pol = polarity(:);
        if numel(pol) ~= numel(t)
            error('source_from_edges:badPolarity', ...
                  'polarity vector must match edge_times length.');
        end
    end

    src = struct('name', name, 'edges', t, 'polarity', pol, 'fs', o.fs, ...
                 'data', o.data, 'labels', {o.labels}, 'time', o.time);
end

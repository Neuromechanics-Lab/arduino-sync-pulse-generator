function src = source_from_continuous(name, signal, fs, varargin)
% SOURCE_FROM_CONTINUOUS A recording that captured the square wave as an
% analog waveform.
%
%   src = source_from_continuous('vicon', sync_channel, 1000)
%   src = source_from_continuous('vicon', sync, 1000, 'data', X, 'labels', L)
%
%   Runs DETECT_EDGES to reduce the waveform to transition times, which is
%   the same object an edge-only recording provides — after this point the
%   two are handled identically.
%
%   Extra name-value pairs are passed through to DETECT_EDGES.
%
%   See also SOURCE_FROM_EDGES, DETECT_EDGES, ALIGN_SOURCES.

    p = inputParser;
    p.KeepUnmatched = true;
    addParameter(p, 'data',   []);
    addParameter(p, 'labels', {});
    addParameter(p, 'time',   []);
    parse(p, varargin{:});
    o = p.Results;

    extra = {};
    f = fieldnames(p.Unmatched);
    for k = 1:numel(f)
        extra{end+1} = f{k};                 %#ok<AGROW>
        extra{end+1} = p.Unmatched.(f{k});   %#ok<AGROW>
    end

    e = detect_edges(signal, fs, extra{:});

    data = o.data;
    if isempty(data), data = signal(:); end
    labels = o.labels;
    if isempty(labels), labels = {'sync'}; end

    src = struct('name', name, 'edges', e.time(:), 'polarity', e.polarity(:), ...
                 'fs', fs, 'data', data, 'labels', {labels}, 'time', o.time);
end

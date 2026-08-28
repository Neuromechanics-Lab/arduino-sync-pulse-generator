function [idx, name] = find_channel(rec, pattern, varargin)
% FIND_CHANNEL Locate analog channels by partial, case-insensitive name.
%
%   idx = find_channel(rec, 'SquareDirect')
%   idx = find_channel(rec, 'Square')                 % may return several
%   [idx, name] = find_channel(rec, 'sol', 'unique', true)
%
%   Vicon writes channel labels with a device prefix and a pin number, e.g.
%   'Voltage.2-SquareDirect'. This matches on any substring so callers can
%   ask for 'SquareDirect' without spelling the rest.
%
%   Name-Value:
%       'unique'  - true to require exactly one match (default false)
%       'exact'   - true for exact label match instead of substring
%
%   Returns [] when nothing matches, unless 'unique' is set, which errors.
%
%   See also LOAD_C3D_ANALOG.

    p = inputParser;
    addParameter(p, 'unique', false, @(x) islogical(x) || isnumeric(x));
    addParameter(p, 'exact',  false, @(x) islogical(x) || isnumeric(x));
    parse(p, varargin{:});
    o = p.Results;

    labels = rec.labels;
    if o.exact
        hits = find(strcmpi(labels, pattern));
    else
        % Match the label WITHOUT its device prefix first, falling back to
        % the full label only if that finds nothing. The prefix would
        % otherwise swallow short muscle abbreviations: Vicon writes channels
        % as 'Voltage.5-TA', and a naive substring search for 'TA' hits the
        % 'ta' in every 'Voltage.', returning the entire device.
        bare = cell(size(labels));
        for k = 1:numel(labels)
            d = strfind(labels{k}, '.');
            if isempty(d)
                bare{k} = labels{k};
            else
                bare{k} = labels{k}(d(end)+1:end);
            end
        end
        hits = find(contains(lower(bare), lower(pattern)));
        if isempty(hits)
            hits = find(contains(lower(labels), lower(pattern)));
        end
    end

    if o.unique
        if isempty(hits)
            error('find_channel:noMatch', ...
                  'No channel matching "%s". Available: %s', ...
                  pattern, strjoin(labels, ', '));
        elseif numel(hits) > 1
            error('find_channel:ambiguous', ...
                  'Pattern "%s" matched %d channels: %s', ...
                  pattern, numel(hits), strjoin(labels(hits), ', '));
        end
    end

    idx = hits;
    if isempty(hits)
        name = {};
    else
        name = labels(hits);
        if o.unique
            name = name{1};
        end
    end
end

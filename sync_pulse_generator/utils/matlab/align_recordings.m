function result = align_recordings(recordings, mode)
% ALIGN_RECORDINGS Align multiple recordings using sync channel cross-correlation.
%
%   result = align_recordings(recordings, mode)
%
%   Inputs:
%       recordings - Cell array of structs, each with fields:
%                      .data        - Table or matrix of recording data
%                      .sync_signal - Vector of sync channel values
%                      .time_vector - Vector of timestamps (seconds)
%                      .fs          - Sampling rate (Hz)
%                      .source_name - (optional) Label string
%                    First entry is the reference.
%
%       mode       - 'offset' | 'merge' | 'bundle'
%                    'offset' : adds aligned_time column, no interpolation
%                    'merge'  : interpolates all to common time base
%                    'bundle' : returns recordings with corrected timestamps
%
%   Output:
%       result - For 'offset'/'bundle': cell array of updated recording structs
%                For 'merge': a table with merged data on common time base
%
%   Example:
%       % Load two recordings manually
%       rec1.data = readtable('vicon.csv');
%       rec1.sync_signal = rec1.data.sync;
%       rec1.fs = 2000;
%       rec1.time_vector = (0:height(rec1.data)-1)' / rec1.fs;
%       rec1.source_name = 'vicon';
%
%       rec2.data = readtable('eeg.csv');
%       rec2.sync_signal = rec2.data.sync;
%       rec2.fs = 500;
%       rec2.time_vector = (0:height(rec2.data)-1)' / rec2.fs;
%       rec2.source_name = 'eeg';
%
%       result = align_recordings({rec1, rec2}, 'merge');

    if nargin < 2; mode = 'offset'; end
    n = length(recordings);
    if n < 2; error('Need at least 2 recordings to align'); end

    ref = recordings{1};
    offsets = zeros(1, n);

    for i = 2:n
        res = find_sync_lag(ref.sync_signal, recordings{i}.sync_signal, ...
                            ref.fs, recordings{i}.fs);
        offsets(i) = res.lag_seconds;
    end

    switch lower(mode)
        case 'offset'
            result = cell(1, n);
            for i = 1:n
                rec = recordings{i};
                aligned_t = rec.time_vector(:) + offsets(i);
                if istable(rec.data)
                    rec.data.aligned_time = aligned_t;
                end
                result{i} = rec;
            end

        case 'bundle'
            result = cell(1, n);
            for i = 1:n
                rec = recordings{i};
                rec.time_vector = rec.time_vector(:) + offsets(i);
                if istable(rec.data)
                    rec.data.aligned_time = rec.time_vector;
                end
                result{i} = rec;
            end

        case 'merge'
            % Find overlapping window
            starts = zeros(1, n);
            ends   = zeros(1, n);
            for i = 1:n
                starts(i) = recordings{i}.time_vector(1) + offsets(i);
                ends(i)   = recordings{i}.time_vector(end) + offsets(i);
            end
            t_start = max(starts);
            t_end   = min(ends);
            if t_start >= t_end
                error('No overlapping time range after alignment');
            end

            common_fs = max(cellfun(@(r) r.fs, recordings));
            common_t  = (t_start : 1/common_fs : t_end)';
            result    = table(common_t, 'VariableNames', {'time'});

            for i = 1:n
                rec = recordings{i};
                aligned_t = rec.time_vector(:) + offsets(i);

                if istable(rec.data)
                    cols = rec.data.Properties.VariableNames;
                    if isfield(rec, 'source_name')
                        prefix = rec.source_name;
                    else
                        prefix = sprintf('rec%d', i);
                    end
                    for c = 1:length(cols)
                        vals = double(rec.data.(cols{c}));
                        % Interpolate NaNs
                        nans = isnan(vals);
                        if any(nans) && ~all(nans)
                            good = find(~nans);
                            vals(nans) = interp1(good, vals(good), find(nans), 'linear', 'extrap');
                        end
                        interped = interp1(aligned_t, vals, common_t, 'linear', NaN);
                        col_name = sprintf('%s_%s', prefix, cols{c});
                        col_name = matlab.lang.makeValidName(col_name);
                        result.(col_name) = interped;
                    end
                end
            end

        otherwise
            error('Unknown mode: %s. Use ''offset'', ''merge'', or ''bundle''.', mode);
    end
end

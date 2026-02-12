function result = find_sync_lag(signal_a, signal_b, fs_a, fs_b)
% FIND_SYNC_LAG Cross-correlate two sync channels and return temporal offset.
%
%   result = find_sync_lag(signal_a, signal_b, fs_a, fs_b)
%
%   If sampling rates differ, the lower-rate signal is resampled up.
%
%   Inputs:
%       signal_a - Sync channel from recording A (vector)
%       signal_b - Sync channel from recording B (vector)
%       fs_a     - Sample rate of signal A (Hz)
%       fs_b     - Sample rate of signal B (Hz)
%
%   Output:
%       result   - Struct with fields:
%                    lag_seconds      - Offset in seconds
%                    lag_samples      - Offset in samples (at common_fs)
%                    peak_correlation - Cross-correlation peak value
%                    confidence       - Peak-to-second-peak ratio
%                    common_fs        - The sample rate used for correlation

    signal_a = signal_a(:);
    signal_b = signal_b(:);
    common_fs = max(fs_a, fs_b);

    % Resample lower-rate signal
    if fs_a < common_fs
        [p, q] = rat(common_fs / fs_a);
        signal_a = resample(signal_a, p, q);
    end
    if fs_b < common_fs
        [p, q] = rat(common_fs / fs_b);
        signal_b = resample(signal_b, p, q);
    end

    % Normalise (zero-mean, unit-variance)
    a = signal_a - mean(signal_a);
    b = signal_b - mean(signal_b);
    sa = std(a); if sa > 0; a = a / sa; end
    sb = std(b); if sb > 0; b = b / sb; end

    % Cross-correlation
    [c, lags] = xcorr(a, b);

    [~, peak_idx] = max(abs(c));
    peak_lag  = lags(peak_idx);
    peak_val  = c(peak_idx);

    % Confidence: ratio of peak to next-highest non-adjacent peak
    abs_c = abs(c);
    adjacency = max(1, round(common_fs * 0.05));  % 50 ms guard
    mask = true(size(abs_c));
    lo = max(1, peak_idx - adjacency);
    hi = min(length(abs_c), peak_idx + adjacency);
    mask(lo:hi) = false;

    if any(mask)
        second_peak = max(abs_c(mask));
        if second_peak > 0
            confidence = abs_c(peak_idx) / second_peak;
        else
            confidence = Inf;
        end
    else
        confidence = Inf;
    end

    result.lag_seconds      = peak_lag / common_fs;
    result.lag_samples      = peak_lag;
    result.peak_correlation = peak_val;
    result.confidence       = confidence;
    result.common_fs        = common_fs;
end

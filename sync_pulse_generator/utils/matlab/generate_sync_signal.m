function [signal, t] = generate_sync_signal(varargin)
% GENERATE_SYNC_SIGNAL Reproduce Arduino PRNG square-wave at a given sample rate.
%
%   [signal, t] = generate_sync_signal()
%   [signal, t] = generate_sync_signal('seed', 42, 'duration_sec', 60, ...)
%
%   Name-Value Parameters:
%       seed         - PRNG seed (default 42, 0 treated as 1)
%       min_high_ms  - Minimum HIGH duration in ms (default 50)
%       max_high_ms  - Maximum HIGH duration in ms (default 500)
%       min_low_ms   - Minimum LOW duration in ms  (default 50)
%       max_low_ms   - Maximum LOW duration in ms  (default 500)
%       duration_sec - Signal duration in seconds   (default 60)
%       sample_rate  - Output sample rate in Hz     (default 1000)
%
%   Returns:
%       signal - Column vector of 0/1 values
%       t      - Column vector of time stamps (seconds)

    p = inputParser;
    addParameter(p, 'seed',         42);
    addParameter(p, 'min_high_ms',  50);
    addParameter(p, 'max_high_ms',  500);
    addParameter(p, 'min_low_ms',   50);
    addParameter(p, 'max_low_ms',   500);
    addParameter(p, 'duration_sec', 60);
    addParameter(p, 'sample_rate',  1000);
    parse(p, varargin{:});
    o = p.Results;

    total_ms     = o.duration_sec * 1000;
    total_samples = floor(o.duration_sec * o.sample_rate);
    signal       = zeros(total_samples, 1);

    % Initialise PRNG state
    state = uint32(o.seed);
    if state == 0; state = uint32(1); end

    elapsed_ms = 0;
    is_high    = false;   % starts LOW, matching Arduino

    while elapsed_ms < total_ms
        % xorshift32 to get next random value
        [state, rval] = xorshift32_next(state);

        if is_high
            dur = random_duration(rval, o.min_high_ms, o.max_high_ms);
        else
            dur = random_duration(rval, o.min_low_ms, o.max_low_ms);
        end

        start_sample = floor(elapsed_ms / 1000 * o.sample_rate) + 1;
        end_sample   = min(floor((elapsed_ms + dur) / 1000 * o.sample_rate), total_samples);

        if is_high && start_sample <= total_samples
            signal(start_sample:end_sample) = 1;
        end

        elapsed_ms = elapsed_ms + dur;
        is_high    = ~is_high;
    end

    t = ((0:total_samples-1)' / o.sample_rate);
end


function [state, val] = xorshift32_next(state)
% XORSHIFT32_NEXT  One step of xorshift32 (matches Arduino implementation).
    state = bitxor(state, bitshift(state, 13, 'uint32'));
    state = bitxor(state, bitshift(state, -17, 'uint32'));
    state = bitxor(state, bitshift(state, 5, 'uint32'));
    val = state;
end


function dur = random_duration(rval, min_ms, max_ms)
% RANDOM_DURATION  Compute duration from PRNG value (matches Arduino, 5ms increments).
    if min_ms >= max_ms
        dur = min_ms;
    else
        steps = uint32((max_ms - min_ms) / 5 + 1);
        dur = min_ms + double(mod(rval, steps)) * 5;
    end
end

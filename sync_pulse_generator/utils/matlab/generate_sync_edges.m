function [times_ms, levels] = generate_sync_edges(duration_s, varargin)
% GENERATE_SYNC_EDGES Edge times of the SIMPLE variant's output.
%
%   [times_ms, levels] = generate_sync_edges(duration_s)
%   [times_ms, levels] = generate_sync_edges(duration_s, 'seed', 42)
%
%   Reproduces sync_pulse_simple.ino: the bare pseudo-random square wave with
%   no timecode frames. Returns toggle times in ms and the level AFTER each
%   toggle, matching GENERATE_SYNC_SIGNAL_TC's shape so the two are
%   interchangeable as template sources.
%
%   The firmware starts LOW and toggles immediately, so the first edge is a
%   rise at t = 0.
%
%   WHY THIS EXISTS ALONGSIDE GENERATE_SYNC_SIGNAL
%   GENERATE_SYNC_SIGNAL returns a SAMPLED waveform at a fixed rate, which is
%   what you want to plot or to cross-correlate. This returns EDGE TIMES,
%   which is what alignment needs — and unlike GENERATE_SYNC_SIGNAL_TC it
%   emits no frames, so it matches recordings made with the simple firmware.
%
%   Getting that distinction wrong does not degrade a lock, it prevents one:
%   the frame variant's intervals are dominated by 5/15/25 ms frame pulses on
%   a finer quantum, so a simple-variant recording matches none of it and the
%   failure reads as corrupt data.
%
%   Name-Value (defaults match sync_pulse_simple.ino):
%       'seed'     42
%       'min_ms'   50
%       'max_ms'   500
%       'step_ms'  5
%
%   See also GENERATE_SYNC_SIGNAL_TC, GENERATE_SYNC_SIGNAL, ALIGN_TEMPLATE.

    p = inputParser;
    addParameter(p, 'seed',    42);
    addParameter(p, 'min_ms',  50);
    addParameter(p, 'max_ms',  500);
    addParameter(p, 'step_ms', 5);
    parse(p, varargin{:});
    o = p.Results;

    state = uint32(o.seed);
    if state == 0, state = uint32(1); end
    steps = uint32((o.max_ms - o.min_ms)/o.step_ms + 1);

    cap = duration_s * 1000;
    n_est = ceil(cap / o.min_ms) + 2;
    times_ms = zeros(n_est, 1);
    levels   = zeros(n_est, 1);

    t = 0;            % first toggle is at t = 0
    level = 1;        % ...and it goes HIGH, matching the firmware
    n = 0;
    while t < cap
        n = n + 1;
        times_ms(n) = t;
        levels(n)   = level;

        % xorshift32, exactly as the firmware computes it
        state = bitxor(state, bitshift(state,  13, 'uint32'));
        state = bitxor(state, bitshift(state, -17, 'uint32'));
        state = bitxor(state, bitshift(state,   5, 'uint32'));

        t     = t + o.min_ms + double(mod(state, steps)) * o.step_ms;
        level = 1 - level;
    end

    times_ms = times_ms(1:n);
    levels   = levels(1:n);
end

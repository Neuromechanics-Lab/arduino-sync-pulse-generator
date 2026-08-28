function [times_ms, levels] = generate_sync_signal_tc(duration_s, run_id, varargin)
% GENERATE_SYNC_SIGNAL_TC Recreate the firmware's hybrid output exactly.
%
%   [times_ms, levels] = generate_sync_signal_tc(duration_s, run_id)
%
%   Returns the toggle times and the level AFTER each toggle, mirroring
%   sync_pulse_generator.ino: output starts LOW with the first toggle (to
%   HIGH) at t=0; every pseudo-random segment draws from the PRNG and is then
%   clamped to end at (tick - lead-in) if it would cross it; the output holds
%   LOW through the lead-in so the frame's first pulse rises exactly ON the
%   tick.
%
%   Unlike GENERATE_SYNC_SIGNAL, which produces the pure pseudo-random train
%   at a fixed sample rate, this returns EDGE TIMES and includes the timecode
%   frames - which is what alignment needs.
%
%   Name-Value (defaults match config.h):
%       'seed' 42, 'min_high' 50, 'max_high' 500, 'min_low' 50,
%       'max_low' 500, 'tc_enabled' true, 'tc_interval_s' 10,
%       'tc_leadin_ms' 20
%
%   See also ALIGN_TEMPLATE, DECODE_TIMECODE.

    p = inputParser;
    addParameter(p, 'seed',          42);
    addParameter(p, 'min_high',      50);
    addParameter(p, 'max_high',      500);
    addParameter(p, 'min_low',       50);
    addParameter(p, 'max_low',       500);
    addParameter(p, 'tc_enabled',    true);
    addParameter(p, 'tc_interval_s', 10);
    addParameter(p, 'tc_leadin_ms',  20);
    parse(p, varargin{:});
    o = p.Results;
    if nargin < 2 || isempty(run_id), run_id = 1; end

    TC_PULSE = 5; TC_PRE_GAP = 10; TC_ZERO = 15; TC_ONE = 25; STEP = 5;

    total_ms = duration_s * 1000;
    cap = ceil(duration_s * 60) + 4096;
    times_ms = zeros(cap, 1);
    levels   = zeros(cap, 1);
    n = 0;

    state = uint32(o.seed);
    if state == 0, state = uint32(1); end

    now_ms  = 0;
    level   = 0;                       % starts LOW
    next_tick = o.tc_interval_s * 1000;

    % The firmware's first toggle (LOW -> HIGH) happens at t=0, before any
    % PRNG draw. Emit it so edge 1 is at 0 ms, matching the reference
    % implementation in utils/python/timecode.py.
    level = 1;
    n = n + 1; times_ms(n) = 0; levels(n) = 1;

    % <= so a frame due exactly at the requested duration is emitted; the
    % loop then ends after it. Python's reference does the same, and a
    % template that stops just short of a frame cannot match a recording
    % that contains it.
    while now_ms <= total_ms
        if o.tc_enabled && now_ms >= next_tick - o.tc_leadin_ms
            % --- frame: first pulse rises exactly on the tick -------------
            elapsed_s = floor(next_tick / 1000);
            chk = bitxor(local_cks(elapsed_s), local_cks(run_id));
            % payload = run_id<<36 | elapsed<<4 | chk, MSB first over 52 bits
            bits = [local_bits(run_id, 16), local_bits(elapsed_s, 32), ...
                    local_bits(chk, 4)];

            now_ms = next_tick;
            % preamble: 3 pulses separated by TC_PRE_GAP
            for k = 1:3
                n = n + 1; times_ms(n) = now_ms; levels(n) = 1;
                now_ms = now_ms + TC_PULSE;
                n = n + 1; times_ms(n) = now_ms; levels(n) = 0;
                if k < 3, now_ms = now_ms + TC_PRE_GAP; end
            end
            % payload: gap encodes the bit, then a pulse
            for b = 1:52
                if bits(b), now_ms = now_ms + TC_ONE; else, now_ms = now_ms + TC_ZERO; end
                n = n + 1; times_ms(n) = now_ms; levels(n) = 1;
                now_ms = now_ms + TC_PULSE;
                n = n + 1; times_ms(n) = now_ms; levels(n) = 0;
            end
            level = 0;
            next_tick = next_tick + o.tc_interval_s * 1000;
            continue;
        end

        % --- pseudo-random segment ----------------------------------------
        [state, rval] = local_xorshift(state);
        if level == 1
            dur = local_dur(rval, o.min_high, o.max_high, STEP);
        else
            dur = local_dur(rval, o.min_low, o.max_low, STEP);
        end

        if o.tc_enabled
            remaining = (next_tick - o.tc_leadin_ms) - now_ms;
            if remaining <= 0
                % Already at or inside the lead-in: hold LOW until the tick.
                % The PRNG draw above still happened, which is what keeps the
                % sequence reproducible. No toggle is emitted here - the
                % previous segment's end edge already marks the lead-in.
                if level ~= 0
                    level = 0;
                    n = n + 1;
                    times_ms(n) = next_tick - o.tc_leadin_ms;
                    levels(n) = 0;
                end
                now_ms = next_tick;
                continue;
            elseif dur > remaining
                % Clamp the segment so it ENDS at the lead-in start. The
                % firmware emits that toggle, then holds LOW into the frame,
                % so the edge at (tick - lead-in) is real and must appear.
                dur = remaining;
            end
        end

        clamped = o.tc_enabled && ...
                  (now_ms + dur >= next_tick - o.tc_leadin_ms - 1e-9);
        now_ms = now_ms + dur;

        if clamped
            % The segment was cut short at the lead-in. Emit a toggle only if
            % the output is currently HIGH and must come down; if it is
            % already LOW it simply stays LOW into the frame.
            %
            % Toggling first and correcting afterwards produced a zero-width
            % pulse here (HIGH and LOW at the same timestamp), which is not
            % something the firmware can emit.
            if level ~= 0
                level = 0;
                n = n + 1;
                if n > numel(times_ms)
                    times_ms(end*2) = 0; levels(end*2) = 0;
                end
                times_ms(n) = now_ms;
                levels(n)   = 0;
            end
            now_ms = next_tick;
            continue;
        end

        level = 1 - level;
        n = n + 1;
        if n > numel(times_ms)
            times_ms(end*2) = 0; levels(end*2) = 0;   % grow
        end
        times_ms(n) = now_ms;
        levels(n)   = level;
    end

    times_ms = times_ms(1:n);
    levels   = levels(1:n);
    % A frame beginning exactly at the requested duration is kept whole, so
    % the template covers the full span rather than stopping mid-frame. This
    % matches utils/python/timecode.py; a template that ends mid-frame would
    % fail to match a recording that contains the whole thing.
end


function [state, val] = local_xorshift(state)
    state = bitxor(state, bitshift(state, 13, 'uint32'));
    state = bitxor(state, bitshift(state, -17, 'uint32'));
    state = bitxor(state, bitshift(state, 5, 'uint32'));
    val = state;
end


function d = local_dur(rval, mn, mx, step)
    if mn >= mx
        d = mn;
    else
        steps = uint32((mx - mn) / step + 1);
        d = double(mn) + double(mod(rval, steps)) * step;
    end
end


function b = local_bits(v, n)
    b = zeros(1, n);
    for i = n:-1:1
        b(i) = mod(v, 2);
        v = floor(v / 2);
    end
end


function c = local_cks(v)
    c = 0;
    for i = 1:8
        c = bitxor(c, mod(v, 16));
        v = floor(v / 16);
    end
end

function frames = decode_timecode(edge_times, varargin)
% DECODE_TIMECODE Recover timecode frames from a recorded edge stream.
%
%   frames = decode_timecode(edge_times)
%   frames = decode_timecode(edges.time, 'edge', 'falling')
%
%   The generator interrupts its pseudo-random train every TC_INTERVAL_S
%   seconds with a frame carrying the box's run ID and its elapsed run time.
%   Cross-correlation and edge matching give a RELATIVE offset between two
%   recordings; a decoded frame gives an ABSOLUTE anchor, so a recording can
%   be placed on the generator's own timeline even if it started late, was
%   paused, or came from a session on another day.
%
%   Frame format (matching config.h and utils/python/timecode.py):
%       preamble  3 pulses of TC_PULSE_MS, separated by TC_PREAMBLE_GAP_MS
%       payload   52 bits, one per gap between pulses, MSB first:
%                 [16-bit run ID][32-bit elapsed seconds][4-bit checksum]
%                 gap of TC_GAP_ZERO_MS = 0, TC_GAP_ONE_MS = 1
%       checksum  XOR of every nibble of the run ID and the elapsed seconds
%
%   Run ID is the box's persistent EEPROM boot counter, so the pair
%   (run_id, elapsed_s) identifies a unique moment across power cycles.
%
%   Inputs:
%       edge_times - Sorted edge times in SECONDS. Either polarity works,
%                    because the frame's pulse width is constant and the
%                    intervals are therefore identical; 'falling' shifts the
%                    anchor back by one pulse width so t_rec is always the
%                    START of the first preamble pulse.
%
%   Name-Value:
%       'edge'      - 'rising' (default) or 'falling'
%       'tol_ms'    - Interval matching tolerance in ms (default 3)
%       'pulse_ms'  - Frame pulse width (default 5)
%       'pre_gap_ms'- Preamble gap (default 10)
%       'zero_ms'   - Gap meaning 0 (default 15)
%       'one_ms'    - Gap meaning 1 (default 25)
%       'require_ok'- true to return only checksum-valid frames (default false)
%
%   Output: struct array, one entry per frame found, with fields
%       .t_rec      - Frame start in RECORDING time (s)
%       .run_id     - Generator boot counter
%       .elapsed_s  - Generator elapsed seconds at the frame
%       .ok         - Checksum passed
%       .offset_s   - elapsed_s - t_rec, the recording's offset from the
%                     generator timeline. Consistent values across frames
%                     mean a clean lock; a trend means clock drift.
%
%   Example:
%       e = detect_edges(rec.data(:, sync_ch), rec.fs);
%       f = decode_timecode(e.time(e.polarity > 0));
%       fprintf('run %d, generator t = %d s at recording t = %.3f s\n', ...
%               f(1).run_id, f(1).elapsed_s, f(1).t_rec);
%
%   See also DETECT_EDGES, GENERATE_SYNC_SIGNAL, ALIGN_TO_TIMECODE.

    p = inputParser;
    addParameter(p, 'edge',       'rising');
    addParameter(p, 'tol_ms',     3);
    addParameter(p, 'pulse_ms',   5);
    addParameter(p, 'pre_gap_ms', 10);
    addParameter(p, 'zero_ms',    15);
    addParameter(p, 'one_ms',     25);
    addParameter(p, 'require_ok', false);
    parse(p, varargin{:});
    o = p.Results;

    e = sort(edge_times(:));
    n = numel(e);

    frames = struct('t_rec', {}, 'run_id', {}, 'elapsed_s', {}, ...
                    'ok', {}, 'offset_s', {});
    if n < 55
        return;   % a whole frame is 55 pulses; nothing to find
    end

    % Pulse-to-pulse interval for each symbol: the gap plus one pulse width.
    pulse   = o.pulse_ms   / 1000;
    pre_int = (o.pre_gap_ms + o.pulse_ms) / 1000;
    int0    = (o.zero_ms    + o.pulse_ms) / 1000;
    int1    = (o.one_ms     + o.pulse_ms) / 1000;
    tol     = o.tol_ms / 1000;

    i = 1;
    while i + 54 <= n
        % Preamble: two equal short intervals.
        d1 = e(i+1) - e(i);
        d2 = e(i+2) - e(i+1);
        if abs(d1 - pre_int) >= tol || abs(d2 - pre_int) >= tol
            i = i + 1;
            continue;
        end

        % Payload: 52 intervals, each a 0 or a 1.
        gaps = diff(e(i+2 : i+54));
        bits = zeros(1, 52);
        good = true;
        for k = 1:52
            if abs(gaps(k) - int0) < tol
                bits(k) = 0;
            elseif abs(gaps(k) - int1) < tol
                bits(k) = 1;
            else
                good = false;
                break;
            end
        end
        if ~good
            i = i + 1;
            continue;
        end

        % Unpack. 52 bits exceeds the 32-bit integer types, and doubles are
        % exact to 2^53, so the fields are assembled in pieces rather than
        % as one integer.
        run_id  = local_bits2num(bits(1:16));
        secs    = local_bits2num(bits(17:48));
        chk     = local_bits2num(bits(49:52));

        anchor = e(i);
        if strcmpi(o.edge, 'falling')
            anchor = anchor - pulse;
        end

        ok = bitxor(local_checksum4(secs), local_checksum4(run_id)) == chk;

        if ~o.require_ok || ok
            frames(end+1) = struct( ...
                't_rec',     anchor, ...
                'run_id',    run_id, ...
                'elapsed_s', secs, ...
                'ok',        ok, ...
                'offset_s',  secs - anchor); %#ok<AGROW>
        end

        i = i + 55;   % skip the frame we just consumed
    end
end


% =========================================================================
function v = local_bits2num(bits)
% MSB-first bit vector to a double. Exact for up to 52 bits.
    v = 0;
    for k = 1:numel(bits)
        v = v * 2 + bits(k);
    end
end


function c = local_checksum4(v)
% XOR of every nibble, matching checksum4 in the firmware and timecode.py.
    c = 0;
    for k = 1:8
        c = bitxor(c, mod(v, 16));
        v = floor(v / 16);
    end
end

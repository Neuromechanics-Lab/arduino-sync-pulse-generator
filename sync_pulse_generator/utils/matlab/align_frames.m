function [frames, run_id] = align_frames(src)
% ALIGN_FRAMES Read the binary timecode frames a recording carries.
%
%   [frames, run_id] = align_frames(src)
%
%   A frame is 52 bits of pulse timing: [16-bit run ID][32-bit elapsed
%   seconds][4-bit checksum]. Where one survives it beats any fingerprint —
%   it states the position outright, checksum-verified, and it is the ONLY
%   thing that identifies WHICH RUN was recorded, since a fixed seed makes
%   every run's waveform identical apart from the frame payload.
%
%   The decoder needs a SINGLE-POLARITY edge stream. Frame pulses have
%   constant width, so rising-only and falling-only both decode; an
%   interleaved both-edges list halves every interval and decodes nothing.
%   Each polarity present is therefore tried separately and the better
%   result kept.
%
%   Returns only checksum-valid frames, and [] for run_id if none decode.
%
%   See also DECODE_TIMECODE, ALIGN_LOCK.

    frames = struct('t_rec', {}, 'run_id', {}, 'elapsed_s', {}, 'ok', {});
    run_id = [];

    t = src.edges(:);
    if numel(t) < 55            % a whole frame is 55 pulses
        return;
    end

    tries = {};
    if isempty(src.polarity)
        tries = {{t, 'rising'}, {t, 'falling'}};
    else
        pol = src.polarity(:);
        if any(pol > 0), tries{end+1} = {t(pol > 0), 'rising'};  end
        if any(pol < 0), tries{end+1} = {t(pol < 0), 'falling'}; end
    end

    best = frames;
    for k = 1:numel(tries)
        edges = sort(tries{k}{1});
        if numel(edges) < 55, continue; end
        try
            got = decode_timecode(edges, 'edge', tries{k}{2}, 'require_ok', true);
        catch
            continue;
        end
        if numel(got) > numel(best)
            best = got;
        end
    end

    frames = best;
    if isempty(frames), return; end

    ids = [frames.run_id];
    u = unique(ids);
    c = arrayfun(@(x) sum(ids == x), u);
    [~, i] = max(c);
    run_id = u(i);
end

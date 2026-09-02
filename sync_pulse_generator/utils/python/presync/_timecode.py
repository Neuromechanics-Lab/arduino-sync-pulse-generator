"""
timecode.py — reference implementation for the sync_pulse_generator's
hybrid pseudo-random + timecode signal.

Two jobs:
  1. generate_template(seed, ...)  — recreate the exact edge sequence the
     firmware emits (PR sections AND timecode frames), for cross-correlation
     alignment. Mirrors sync_pulse_generator.ino exactly.
  2. decode_frames(edge_times_s, ...) — find timecode frames in a list of
     recorded edge timestamps and return (recording_time, elapsed_seconds)
     anchor pairs. Works on rising OR falling edge streams (constant frame
     pulse width makes the intervals identical); pass edge='falling' to
     correct anchors by the pulse width.

Frames start EXACTLY on the interval tick: the random segment that would
cross (tick - TC_LEADIN_MS) is cut short there, the output holds LOW for the
lead-in, and the first preamble pulse rises on the tick. A decoded frame's
t_rec therefore marks exactly `elapsed_s` seconds of generator time.

Frame format (all times ms, defaults match config.h):
  preamble: 3 pulses (5 ms HIGH) separated by 10 ms gaps
  payload:  52 bits as gaps between pulses — 15 ms = 0, 25 ms = 1 —
            MSB-first: [16-bit run ID][32-bit elapsed seconds][4-bit
            checksum]. Run ID is the box's persistent EEPROM boot counter
            (increments on every PRNG restart), so (run_id, elapsed_s)
            uniquely identifies every emitted moment across power cycles.
            Checksum = XOR of all nibbles of run ID and elapsed seconds.

Self-test: `python3 timecode.py` simulates 95 s of signal and verifies the
decoder recovers every frame exactly.
"""

# ---- firmware constants (keep in sync with config.h) ----
TC_PULSE_MS = 5
TC_PREAMBLE_GAP_MS = 10
TC_GAP_ZERO_MS = 15
TC_GAP_ONE_MS = 25
TC_LEADIN_MS = 20                # forced LOW before each frame tick
STEP_MS = 5                      # randomDuration granularity


def _xorshift32(state):
    state ^= (state << 13) & 0xFFFFFFFF
    state ^= state >> 17
    state ^= (state << 5) & 0xFFFFFFFF
    return state & 0xFFFFFFFF


def checksum4(v):
    c = 0
    for _ in range(8):
        c ^= v & 0xF
        v >>= 4
    return c


def frame_durations(elapsed_s, run_id=1):
    """Alternating [pulse, gap, pulse, ...] durations (ms) for one frame."""
    chk = checksum4(elapsed_s) ^ checksum4(run_id)
    payload = (run_id << 36) | (elapsed_s << 4) | chk
    out = [TC_PULSE_MS, TC_PREAMBLE_GAP_MS, TC_PULSE_MS, TC_PREAMBLE_GAP_MS,
           TC_PULSE_MS]
    for k in range(52):
        bit = (payload >> (51 - k)) & 1
        out.append(TC_GAP_ONE_MS if bit else TC_GAP_ZERO_MS)
        out.append(TC_PULSE_MS)
    return out


def generate_template(seed, duration_s,
                      min_high=50, max_high=500, min_low=50, max_low=500,
                      tc_enabled=True, tc_interval_s=10, run_id=1,
                      tc_leadin_ms=TC_LEADIN_MS):
    """Return (times_ms, levels): the level after each toggle, from t=0.

    Mirrors the firmware exactly:
      * output starts LOW, first toggle (to HIGH) at t=0
      * every pseudo-random segment draws from the PRNG, then is clamped to
        end at (tick - lead-in) if it would cross it; the output then holds
        LOW through the lead-in and the frame starts ON the tick
      * a LOW->HIGH toggle due less than TC_PULSE_MS before the lead-in is
        skipped (no draw) — the output just stays LOW into the lead-in
      * the frame consumes no PRNG draws; the LOW after it is a normal
        (clamped) draw
    """
    state = seed if seed != 0 else 1

    def draw(mn, mx):
        nonlocal state
        if mn >= mx:
            return mn
        state = _xorshift32(state)
        steps = (mx - mn) // STEP_MS + 1
        return mn + (state % steps) * STEP_MS

    t = 0.0
    level = 0
    times, levels = [], []
    period = tc_interval_s * 1000.0
    next_due = period
    end_ms = duration_s * 1000.0

    def emit(new_level, dur):
        nonlocal t, level
        times.append(t)
        levels.append(new_level)
        level = new_level
        t += dur

    def extend(dur):                      # LOW continues, no edge
        nonlocal t
        t += dur

    def schedule(new_level):
        """Set new_level now with a PR draw; True if the lead-in follows."""
        d = draw(min_high, max_high) if new_level else draw(min_low, max_low)
        seg, pending = d, False
        if tc_enabled:
            room = (next_due - tc_leadin_ms) - t
            if d > room:
                seg, pending = room, True
        if new_level != level:
            emit(new_level, seg)
        else:
            extend(seg)
        return pending

    pending = False
    while t < end_ms:
        if pending:
            # lead-in: LOW until the tick, then the frame ON the tick
            if level:
                emit(0, next_due - t)
            else:
                extend(next_due - t)
            for i, d in enumerate(frame_durations(int(next_due // 1000), run_id)):
                emit(1 if i % 2 == 0 else 0, d)
            next_due += period
            pending = schedule(0)             # post-frame LOW (clamped if needed)
            continue
        new = 1 - level
        if tc_enabled and new == 1 and (next_due - tc_leadin_ms) - t < TC_PULSE_MS:
            pending = True                    # too close for a real pulse
            continue
        pending = schedule(new)
    return times, levels


def rising_edges(times, levels):
    return [t for t, l in zip(times, levels) if l == 1]


def decode_frames(edge_times_s, edge='rising', tol_ms=3.0):
    """Find timecode frames in a sorted list of edge timestamps (seconds).

    Works on a single-polarity edge stream (rising or falling — the constant
    frame pulse width makes the inter-edge intervals identical). Returns a
    list of dicts: {'t_rec': anchor time in the recording (s, at the FIRST
    preamble pulse's edge), 'elapsed_s': decoded generator elapsed seconds,
    'ok': checksum valid}. If edge='falling', anchors are corrected back by
    the pulse width so t_rec still refers to the pulse START.
    """
    e = list(edge_times_s)
    pre = (TC_PULSE_MS + TC_PREAMBLE_GAP_MS) / 1000.0     # 15 ms
    b0 = (TC_PULSE_MS + TC_GAP_ZERO_MS) / 1000.0          # 20 ms
    b1 = (TC_PULSE_MS + TC_GAP_ONE_MS) / 1000.0           # 30 ms
    tol = tol_ms / 1000.0
    out = []
    i = 0
    while i + 54 < len(e):
        d1 = e[i + 1] - e[i]
        d2 = e[i + 2] - e[i + 1]
        if abs(d1 - pre) < tol and abs(d2 - pre) < tol:
            bits = []
            for k in range(52):
                dk = e[i + 3 + k] - e[i + 2 + k]
                if abs(dk - b0) < tol:
                    bits.append(0)
                elif abs(dk - b1) < tol:
                    bits.append(1)
                else:
                    bits = None
                    break
            if bits is not None:
                val = 0
                for b in bits:
                    val = (val << 1) | b
                run_id = val >> 36
                secs = (val >> 4) & 0xFFFFFFFF
                chk = val & 0xF
                anchor = e[i]
                if edge == 'falling':
                    anchor -= TC_PULSE_MS / 1000.0
                out.append({'t_rec': anchor, 'run_id': run_id,
                            'elapsed_s': secs,
                            'ok': (checksum4(secs) ^ checksum4(run_id)) == chk})
                i += 55
                continue
        i += 1
    return out


ANCHOR_TOL_MS = 10.0   # frames start ON the tick; anchors should agree to
                       # within the recorder's edge-timing resolution


def align_to_timecode(frames, require_ok=True, expect_run=None,
                      max_pulse_ms=None):
    """Place a recording on the generator's own timeline.

    WHAT A RUN IS, AND WHY IT MATTERS

    The generator's elapsed clock is not a wall clock. It counts from the
    start of the current RUN, and every run start increments the persistent
    run ID. A run starts when:

      * the box boots in FREE RUN mode (output begins immediately);
      * a trigger edge arrives on TRIG IN while in TRIG RUN mode (output is
        held LOW until then, so elapsed 0 IS the trigger);
      * the mode switch is moved to FREE RUN;
      * a serial 'start' or 'restart' command is issued.

    So elapsed_s means "seconds since this run began", and what began the run
    depends on the mode. In FREE RUN, elapsed 0 is power-up. In TRIG RUN,
    elapsed 0 is the trigger pulse - the useful case for starting several
    devices together from one master pulse.

    Because the run ID changes at every one of those events, TWO RECORDINGS
    SHARE A TIMELINE ONLY IF THEIR RUN IDS MATCH. Comparing elapsed values
    across different run IDs is meaningless: they count from different zeros.
    A run ID change is therefore treated as a hard boundary, and each run is
    reported separately rather than fitted through.

    ANCHOR ACCURACY

    Frames start EXACTLY on the interval tick (the firmware cuts the random
    segment short and holds LOW for a lead-in), so every anchor is exact:
    t_rec of a frame IS elapsed_s of generator time, to the millisecond.
    Offsets (elapsed - t_rec) should therefore agree across all frames to
    within the recorder's edge-timing resolution (ANCHOR_TOL_MS):

      * the offset is the mean of all anchors;
      * drift is a least-squares slope through all anchors, reported only
        when it both exceeds the anchor tolerance over the span observed
        and clears the slope's own noise floor by 3x;
      * residuals above ANCHOR_TOL_MS about the fit mean a frame was
        mis-decoded or the recorder's timing is coarser than expected.

    `max_pulse_ms` is accepted for backward compatibility and ignored: it
    parameterised the emission jitter of firmware that emitted frames late.

    Returns a dict with 'runs' (one entry per run ID), 'primary' (the run
    with the most frames), 'offset_s', 'to_generator'/'to_recording'
    callables, and 'warnings'.
    """
    if not frames:
        raise ValueError(
            "No timecode frames were decoded. Either the generator had "
            "timecode disabled (DEFAULT_TC_ENABLED 0), the recording is "
            "shorter than one frame interval, or the edge detector missed "
            f"the frame pulses - they are only {TC_PULSE_MS} ms wide.")

    if require_ok:
        frames = [f for f in frames if f['ok']]
        if not frames:
            raise ValueError(
                "Frames were found but every checksum failed. The frame "
                "timing constants here may not match the firmware that "
                "produced the recording - check TC_* in config.h.")

    if expect_run is not None:
        frames = [f for f in frames if f['run_id'] == expect_run]
        if not frames:
            raise ValueError(f"No frames carry run ID {expect_run}.")

    warnings = []
    order = []
    for f in frames:
        if f['run_id'] not in order:
            order.append(f['run_id'])

    runs = []
    for rid in order:
        sel = [f for f in frames if f['run_id'] == rid]
        t = [f['t_rec'] for f in sel]
        el = [float(f['elapsed_s']) for f in sel]
        offset, drift_ppm, residual_ms, drift_resolvable = _anchor_fit(t, el)
        runs.append({
            'run_id': rid,
            'n_frames': len(sel),
            't_rec_first': min(t), 't_rec_last': max(t),
            'elapsed_first': min(el), 'elapsed_last': max(el),
            'offset_s': offset,
            'drift_ppm': drift_ppm,
            'drift_resolvable': drift_resolvable,
            'residual_ms': residual_ms,
        })

    primary = max(runs, key=lambda r: r['n_frames'])

    if len(order) > 1:
        warnings.append(
            f"{len(order)} different run IDs appear in this recording "
            f"({', '.join(str(x) for x in order)}). The generator restarted "
            f"mid-recording - a trigger arrived, the mode switch moved, or it "
            f"was restarted over serial. Each run counts elapsed time from its "
            f"own zero, so they CANNOT be placed on one timeline. Run "
            f"{primary['run_id']} ({primary['n_frames']} frames) was used; "
            f"split the recording at the boundary to use the others.")

    if primary['n_frames'] < 2:
        warnings.append(
            "Only one frame was decoded, so the offset rests on a single "
            "anchor and no drift estimate is possible. Record for at least "
            "two frame intervals for a checkable alignment.")

    span = max(primary['t_rec_last'] - primary['t_rec_first'], 1e-9)
    if primary['drift_resolvable']:
        implied_ms = abs(primary['drift_ppm']) * span / 1000.0
        warnings.append(
            f"Clock rate differs by {primary['drift_ppm']:.0f} ppm between the "
            f"generator and the recorder "
            f"({primary['drift_ppm'] * 60 / 1000:.1f} ms per minute, "
            f"{implied_ms:.0f} ms over the {span:.0f} s observed). A constant "
            f"offset will not hold across a long trial.")

    if primary['residual_ms'] > ANCHOR_TOL_MS:
        warnings.append(
            f"Frame anchors scatter by up to {primary['residual_ms']:.0f} ms "
            f"about the fit, more than the {ANCHOR_TOL_MS:.0f} ms anchor "
            f"tolerance. Frames start exactly on the tick, so this means a "
            f"frame was mis-decoded or the recorder's edge timing is coarser "
            f"than expected.")

    offset = primary['offset_s']
    return {
        'n_runs': len(order),
        'run_ids': order,
        'runs': runs,
        'primary': primary,
        'offset_s': offset,
        'to_generator': lambda t_rec: t_rec + offset,
        'to_recording': lambda t_gen: t_gen - offset,
        'warnings': warnings,
    }


def _anchor_fit(t, el):
    """Offset + drift from exact anchors.

    Anchors are exact (frames start on the tick), so all of them carry equal
    weight: offset = mean(elapsed - t_rec), drift = least-squares slope of
    the offsets against recording time. Returns (offset_s, drift_ppm,
    max_residual_ms, resolvable); drift_ppm is 0.0 unless `resolvable`.
    """
    n = len(t)
    offs = [e - x for x, e in zip(t, el)]
    offset = sum(offs) / n
    span = (max(t) - min(t)) if n else 0.0
    if n < 3 or span <= 0:
        resid = (max(offs) - min(offs)) * 1000.0 if n > 1 else 0.0
        return offset, 0.0, resid, False

    mx = sum(t) / n
    sxx = sum((x - mx) ** 2 for x in t)
    slope = sum((x - mx) * (o - offset) for x, o in zip(t, offs)) / sxx
    intercept = offset - slope * mx
    resid = [o - (slope * x + intercept) for x, o in zip(t, offs)]
    resid_ms = max(abs(r) for r in resid) * 1000.0
    drift_ppm = slope * 1e6

    spread = max(resid) - min(resid)
    slope_noise_ppm = (spread / span) * 1e6
    resolvable = (abs(drift_ppm) * span / 1000.0 > ANCHOR_TOL_MS
                  and abs(drift_ppm) > 3 * slope_noise_ppm)
    return offset, (drift_ppm if resolvable else 0.0), resid_ms, resolvable


def split_runs(frames):
    """Group decoded frames by run ID, in order of first appearance.

    A run ID change marks a generator restart (trigger, mode switch, or
    serial restart). Recordings spanning a boundary must be split there
    before alignment, because elapsed times on either side count from
    different zeros.

    Returns a list of (run_id, [frames]) pairs.
    """
    order = []
    for f in frames:
        if f['run_id'] not in order:
            order.append(f['run_id'])
    return [(rid, [f for f in frames if f['run_id'] == rid]) for rid in order]


if __name__ == '__main__':
    times, levels = generate_template(seed=42, duration_s=95, run_id=137)
    rises = [t / 1000.0 for t in rising_edges(times, levels)]
    frames = decode_frames(rises)
    expect = list(range(10, 95, 10))
    got = [f['elapsed_s'] for f in frames]
    assert all(f['ok'] for f in frames), "checksum failures"
    assert got == expect, f"decode mismatch: {got} != {expect}"
    assert all(f['run_id'] == 137 for f in frames), "run_id mismatch"
    # frames start ON the tick: anchor == elapsed exactly
    assert all(abs(f['t_rec'] - f['elapsed_s']) < 1e-9 for f in frames), \
        "frame anchor not on the tick"
    # the random train around frames still never imitates a preamble
    # (cut-short stub + lead-in = 25 ms interval, never 15)
    # falling-edge stream decodes identically (constant pulse width)
    falls = [(t + TC_PULSE_MS) / 1000.0 for t in rising_edges(times, levels)]
    frames_f = decode_frames(falls, edge='falling')
    assert [f['elapsed_s'] for f in frames_f] == expect
    assert all(abs(a['t_rec'] - b['t_rec']) < 1e-9
               for a, b in zip(frames, frames_f)), "falling-edge anchor off"

    # alignment: single run
    a = align_to_timecode(frames)
    assert a['n_runs'] == 1, f"expected 1 run, got {a['n_runs']}"
    assert a['primary']['run_id'] == 137
    assert abs(a['to_recording'](a['to_generator'](3.5)) - 3.5) < 1e-9

    # alignment: a mid-recording restart must be reported, not averaged over.
    # Run 137 ends and run 138 starts from its own zero.
    t2, l2 = generate_template(seed=42, duration_s=45, run_id=138)
    r2 = [t / 1000.0 + 100.0 for t in rising_edges(t2, l2)]
    frames2 = decode_frames(r2)
    mixed = frames + frames2
    a2 = align_to_timecode(mixed)
    assert a2['n_runs'] == 2, f"expected 2 runs, got {a2['n_runs']}"
    assert a2['run_ids'] == [137, 138], a2['run_ids']
    assert any('CANNOT be placed on one timeline' in w for w in a2['warnings'])
    assert a2['primary']['run_id'] == 137          # more frames
    parts = split_runs(mixed)
    assert [p[0] for p in parts] == [137, 138]
    assert len(parts[1][1]) == len(frames2)

    # selecting the second run explicitly gives that run's own offset
    a3 = align_to_timecode(mixed, expect_run=138)
    assert a3['n_runs'] == 1 and a3['primary']['run_id'] == 138
    # exact anchors: the offset is the applied shift, and no residual/drift
    assert abs(a3['offset_s'] + 100.0) < 1e-9, a3['offset_s']
    assert a3['primary']['residual_ms'] < 1e-6 and not a3['primary']['drift_resolvable']
    # a 200 ppm recorder clock must be detected from exact anchors
    slow = [{**f, 't_rec': f['t_rec'] * (1 + 200e-6)} for f in frames]
    a4 = align_to_timecode(slow)
    assert a4['primary']['drift_resolvable'] and abs(a4['primary']['drift_ppm'] + 200) < 5, \
        a4['primary']

    print(f"self-test OK: {len(frames)} frames decoded "
          f"({got[0]}..{got[-1]} s), edge-polarity correction verified, "
          f"run-boundary handling verified ({a2['n_runs']} runs detected)")

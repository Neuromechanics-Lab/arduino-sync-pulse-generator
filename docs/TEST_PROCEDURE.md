# PRE-Sync — Acceptance test procedure

What a built unit must demonstrate before it is used for data collection, and
what fills the *TBM* entries in the datasheet.

Record results in `docs/test-results/<serial>-<date>.md`. A unit with an
incomplete sheet is not qualified.

## 1. Visual and continuity

- [ ] All connectors seated; no strain on solder joints.
- [ ] Copper foil lining bonded at the ground screw, **one point only** — a
      second bond makes a ground loop.
- [ ] Continuity: each BNC shield to chassis ground.
- [ ] Isolation: each BNC centre to every other centre, open circuit.

## 2. Power-on

- [ ] Draws power without excessive current.
- [ ] USB enumerates as a serial device.
- [ ] `config` returns the running configuration.
- [ ] Onboard LED (Leonardo pin 13) mirrors the signal.

## 3. Output waveform — oscilloscope

For each of the eight panel outputs:

- [ ] Amplitude 5 V ±0.25 V, unloaded.
- [ ] Amplitude under a realistic recorder load. **Record the value.**
- [ ] Rise time, 10–90%. **Record.**
- [ ] Fall time, 90–10%. **Record.**
- [ ] No ringing or overshoot beyond 10%.

Then, across channels:

- [ ] Channel-to-channel skew, all eight simultaneously. **Record the worst
      pair.** This bounds the accuracy of anything aligned between two devices
      fed from different outputs.

## 4. Independent driver claim

The datasheet states that loading one channel does not disturb the others.
This is a design claim and must be demonstrated, not asserted:

- [ ] Short one output to ground. Verify the other seven are unaffected in
      amplitude and timing.
- [ ] Load one output heavily (e.g. 100 Ω). Same check.
- [ ] Confirm the shorted channel recovers when the fault is removed.

## 5. Generator clock accuracy

Every alignment the device supports is bounded by this number.

- [ ] Measure actual pulse durations against a calibrated reference over at
      least 10 minutes.
- [ ] Compute the mean error in ppm. **Record.**
- [ ] Confirm durations land on the 5 ms quantum.

## 6. Timecode

- [ ] Enable frames (`tc on`). Confirm one frame per interval.
- [ ] Decode with `utils/python/timecode.py`; checksums pass.
- [ ] Verify the frame's first edge marks exactly `elapsed` seconds.
- [ ] Power-cycle; confirm the run ID incremented and persists.

## 7. Trigger modes

For each of `start`, `toggle`, `gate`:

- [ ] Behaves as specified in `docs/INTERFACE.md` §5.
- [ ] With TRIG unconnected, no false trigger over 10 minutes.
- [ ] Lead-in marker (`mark on`): one clean pulse, correct pause, run clock
      starting at the marker's leading edge.

## 8. Mode switch fail-safe

- [ ] Disconnect the mode switch entirely. **The box must free-run**, not sit
      silent. This is the single most important failure behaviour in the
      device.

## 9. End-to-end

- [ ] Record the signal on two or more systems at different sample rates, at
      least one edge-only.
- [ ] Include a FREE→TRIG change so two run IDs appear in one session.
- [ ] Analyse with `python3 -m presync run`. Confirm every stream locates and
      reports drift, jitter and capture.
- [ ] Multi-hour run: confirm rate estimation holds where it matters.

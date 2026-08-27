# Sync Pulse Generator

Pseudo-random square-wave sync pulse generator on an ATmega32U4 (Pro Micro /
Leonardo), for cross-correlation-based temporal alignment of multi-device
recordings (Vicon, EEG, DAQ, audio, video). Hardware enclosure: the
**PRE-Sync** box (`../trigger-box/`) — 2 gain-controlled banks of 3 BNC
outputs, TRIG input + FREE/TRIG run switch.

All output pins carry the same 5 V / 0 V signal. HIGH and LOW durations are
drawn pseudo-randomly (xorshift32, fixed seed) from configurable ranges —
the same seed always produces the same sequence, so the expected waveform
can be recreated offline and any recording aligned to it by
cross-correlation (`utils/R/sync_align.R`).

## Timecode frames (hybrid mode, default ON)

Every 10 s (configurable) the pseudo-random train is interrupted by one
**timecode frame** encoding elapsed seconds since the PRNG started —
constant 5 V amplitude, information purely in pulse timing. **Frames start
exactly on the tick:** the random segment that would cross the tick is cut
short 20 ms early, the output holds LOW for that lead-in, and the first
preamble pulse rises ON the tick — so a decoded frame's first edge marks
precisely `elapsed` seconds of generator time (ms-accurate anchors, not
"somewhere in that second").

```
preamble                 payload: 52 bits as gaps between 5 ms pulses
P──10──P──10──P ── g₀ ──P── g₁ ──P── ... ──g₅₁──P
                  15 ms = 0   25 ms = 1
bits, MSB first:  [16-bit run ID][32-bit elapsed seconds][4-bit checksum]
checksum: XOR of all 4-bit nibbles of run ID and elapsed seconds
```

**Run ID** is a persistent EEPROM counter that increments on every PRNG
(re)start — power-up, `start`, `restart`, `seed`, `reset`. Since the fixed
seed makes every run's waveform identical, the run ID is what tells run 731's
`t=50 s` apart from run 732's: **(run ID, elapsed) uniquely identifies every
moment the box has ever emitted.** A recording found years later self-reports
which session it belongs to. (Counter wraps at 65535; it is stored outside
the config block, so `save`/`reset` never touch it.)

Why: with a fixed seed the PR train itself already encodes absolute position
(any chunk cross-correlates to one offset in the reconstructed template) —
frames add three practical things on top: **no-compute anchors** (decoding
one frame beats correlating against an hours-long template), **drift-immune
point anchors** (each frame decodes independently of accumulated sample-rate
error), and **run identity** (see Run ID above — the one thing the PR train
cannot provide, since every run's waveform is identical). Frames are deterministic and consume
no PRNG draws, so the complete hybrid signal is still exactly reproducible
from (seed, config): cross-correlation works across frames like any other
signal — they're simply part of the fingerprint (and each frame differs, so
no periodicity artifact).

Design rules baked in:
- PR durations (default min 50 ms) can never imitate frame timing
  (5–25 ms) — preambles are unambiguous. The cut-short segment before a
  frame can be arbitrarily brief, which is why the lead-in is 20 ms: a
  short HIGH stub then the lead-in gives a 25 ms edge interval — neither a
  preamble (15) nor a bit (20/30).
- The PRNG draw for the cut-short segment still happens, so the template
  generator reproduces the clamp exactly from (seed, config).
- **Edge-polarity friendly:** frame pulses have constant width, so a
  falling-edge-only recording decodes identically; its anchors are exactly
  `TC_PULSE_MS` (5 ms) late, corrected by `edge="falling"` in the decoders.
  In an unlabeled edge stream, the frame's 5 ms intervals even identify
  which edges are rises.
- Cameras/LED pods can't resolve frame gaps — they don't need to: they
  align by cross-correlation against the recreated template as always.

## FREE RUN / TRIG RUN (the rear-panel switch)

The PRE-Sync box's SPDT toggle selects the run mode (read live — flipping
it mid-session acts immediately):

- **FREE RUN** — output starts at power-up, exactly as before.
- **TRIG RUN** — outputs hold LOW until a rising edge arrives on the
  **TRIG IN** BNC, then a fresh run starts (new run ID, elapsed = 0).
  Chain several boxes from one master pulse and they start in sync; each
  box still stamps its own run ID. Once running, further TRIG edges are
  ignored — re-arm by flipping the switch or power-cycling.

Wiring (see `config.h`): switch common → pin 3, FREE-throw → GND;
TRIG BNC center → ~1 kΩ series resistor → pin 2. The TRIG input must sit
LOW ≥ 20 ms before an edge counts, so an unconnected jack can never
false-trigger (an idle master holding 0 V arms it). Pins 2 and 3 are
excluded from the output set; all other pins still carry the signal.

## Serial commands (115200 baud)

```
high <min> <max>   low <min> <max>    seed <value>
tc on|off          tcint <seconds>    save
start | stop | restart | reset | config | help
```

`tc on` / `tcint` take effect immediately, on the run's interval grid
(never a burst of overdue frames); `tcint` minimum is 2 s (a frame is
~1.65 s). `save` persists everything (including timecode settings) to
EEPROM.
EEPROM magic is 0xA8 — older saved configs (0xA7) are invalidated and
defaults reload on first boot after this firmware update.

## Concept figure

`docs/timecode_figure.{svg,png}` — the hybrid signal at three zoom levels
(12 s overview → one frame with its fields bracketed → preamble and first
bits at ms scale), generated bit-exact from the reference implementation by
`utils/python/timecode_figure.py`. `timecode_figure_bare.*` is the same
waveform with no labels, for annotating from scratch. SVG stays editable.

## Offline tools (`utils/`)

Full documentation, worked examples for two and for many signals, and the
function reference across all three languages: **[`utils/README.md`](utils/README.md)**.

Three ways to align, for different situations:

- **Edge timing** (`edge_sync.py`, `detect_edges`/`edge_delay` in all three
  languages) — measures the delay transition by transition, with error bars.
  The right tool when one copy of the square wave has been through an EMG
  amplifier: the high-pass turns each step into a spike, so the waveforms no
  longer resemble each other but their edge *times* still line up.
- **Timecode frames** (`timecode.py`, `decode_timecode`, `align_to_timecode`)
  — absolute anchors and run identity. `generate_template()` recreates the
  exact hybrid edge sequence from (seed, config); `decode_frames()` extracts
  anchors from recorded edge times; `align_to_timecode()` maps a recording
  onto the generator's timeline and refuses to fit across a run boundary.
  Run `python timecode.py` for a round-trip self-test.
- **Cross-correlation** (`sync_align.*`) — whole-waveform alignment when both
  copies look alike.

Also here: a dependency-free C3D/CSV reader, a standard EMG processing chain
with quality checks (flat and railed channels are flagged, not silently
processed), and a four-panel visual QC figure.

## Build

```
arduino-cli compile --fqbn arduino:avr:leonardo .
arduino-cli compile --fqbn arduino:avr:micro \
  --build-property "compiler.cpp.extra_flags=-DBOARD_PRO_MICRO" .
```

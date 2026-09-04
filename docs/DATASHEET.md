# PRE-Sync — Datasheet

A pseudo-random square-wave generator for post-hoc alignment of independent
recording systems.

**Status: preliminary.** Values marked *TBM* (to be measured) are design
intent, not measurements. See `docs/TEST_PROCEDURE.md`.

## Description

PRE-Sync emits a pseudo-random square wave simultaneously on up to 18
independently driven outputs. Because the waveform is fully determined by
(seed, configuration), it can be regenerated offline and used as ground truth:
every recorded edge has a known true time, and the difference is the
recorder's error.

That distinguishes it from a plain trigger pulse. A single pulse marks one
instant; a non-repeating pattern lets any segment of a recording be located
absolutely, so offset, clock drift, jitter and data loss can be separated and
measured rather than assumed.

Optional embedded timecode frames carry a run ID and elapsed seconds, giving
absolute position with no pattern search and identifying which run was
recorded.

## Absolute maximum ratings

| Parameter | Min | Max | Unit |
|---|---|---|---|
| Supply voltage (barrel) | 7 | 12 | V |
| Current per output pin | — | 40 | mA |
| Total current, all pins | — | 200 | mA |
| Operating temperature | 0 | 50 | °C |

Exceeding these may cause permanent damage. Sustained operation should stay
within the recommended conditions below.

## Recommended operating conditions

| Parameter | Typ | Notes |
|---|---|---|
| Supply voltage | 9 V | or USB 5 V |
| Current per output | ≤ 20 mA | ATmega32U4 recommendation |
| Output load | ≥ 1 kΩ | high-impedance recorder inputs |

## Electrical characteristics

| Parameter | Value | Notes |
|---|---|---|
| Output HIGH | 5.0 V nominal | 5 V CMOS, hardware fixed |
| Output LOW | 0.0 V nominal | |
| Rise time | *TBM* | into a realistic load |
| Fall time | *TBM* | |
| Channel-to-channel skew | *TBM* | across all outputs |
| Output impedance | series resistor per channel | value *TBM* |

> **3.3 V equipment**: outputs are 5 V. Use a divider or level shifter.
> TTL inputs (HIGH above 2.4 V) accept 5 V directly.

## Timing characteristics

| Parameter | Value | Notes |
|---|---|---|
| Pulse duration range | 50–500 ms | HIGH and LOW independently drawn |
| Duration quantum | 5 ms | the finest step emitted |
| Timecode interval | 10 s | when enabled |
| Timecode pulse width | 5 ms | |
| Generator clock accuracy | *TBM* | bounds every alignment |
| Trigger arm time | 20 ms | LOW hold before an edge counts |

## Interfaces

| Connector | Qty | Type |
|---|---|---|
| Sync output | 8 wired (18 available) | BNC bulkhead |
| TRIG IN | 1 | BNC bulkhead |
| Mode select | 1 | SPDT toggle |
| Power | 1 | 5.5×2.1 mm barrel |
| Chassis ground | 1 | 10-32 screw |
| Configuration | 1 | USB CDC serial |

Full pinout, signal levels and command set: `docs/INTERFACE.md`.

## Mechanical

| Parameter | Value |
|---|---|
| Internal envelope | 168 × 45 × 31 mm |
| Wall thickness | 3 mm |
| Enclosure | 3D printed, four parts |
| Mass | *TBM* |

## Failure behaviour

Design choices that determine how the device fails, which for a timing
reference matters more than how it performs when everything works:

- **A missing or failed-open mode switch reads FREE RUN**, so the box emits.
  Silence is the worst failure available here, because it is only discovered
  later, in analysis, when nothing aligns.
- **An unconnected TRIG jack cannot false-trigger**: the input must sit LOW
  for 20 ms before a rising edge counts.
- **Each output has its own driver pin**, so loading or shorting one channel
  does not disturb the others.
- **The run ID increments on every PRNG restart** and persists in EEPROM, so
  two runs are never confused even though a fixed seed makes their waveforms
  identical.

## Reproducibility

The emitted waveform is regenerated bit-identically by three independent
implementations (Python, MATLAB, R) in `sync_pulse_generator/utils/`.

## Documents

| Document | Contents |
|---|---|
| `docs/INTERFACE.md` | Pinout, levels, serial commands |
| `docs/BOM.csv` | Bill of materials |
| `docs/wiring/presync-harness.png` | Panel wiring |
| `docs/TEST_PROCEDURE.md` | Acceptance tests |
| `docs/api/` | Analysis toolkit API |

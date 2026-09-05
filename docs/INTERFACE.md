# PRE-Sync — Interface Control Document

Connector pinout, signal levels and the serial command set.

**Generated from the firmware sources — do not edit by hand.**
Regenerate with `python3 tools/gen_interface_doc.py` after changing
`config.h` or the command parser.

## 1. Electrical

| Property | Value | Notes |
|---|---|---|
| Logic family | 5 V CMOS | ATmega32U4, hardware fixed |
| Output HIGH | 5.0 V nominal | |
| Output LOW | 0.0 V nominal | |
| Max current per pin | 40 mA absolute, **20 mA recommended** | ATmega32U4 datasheet |
| Max total across all pins | 200 mA | package limit, not per-pin sum |
| Output impedance | series resistor per channel | sized at build; see BOM |

> **3.3 V equipment**: these outputs are 5 V. Use a divider or level
> shifter. Equipment with TTL inputs (HIGH above 2.4 V) accepts 5 V
> directly.

> **Every output carries the same signal simultaneously.** Each has its
> own driver pin, so loading or shorting one channel does not disturb
> the others.

## 2. Pin assignment

Two board variants. Select Pro Micro with `-DBOARD_PRO_MICRO`.

| Board | Panel outputs | Event channel | Reserved inputs |
|---|---|---|---|
| Arduino Leonardo | 8 | 9 | 2, 3 |
| Pro Micro ATmega32U4 | 8 | 9 | 2, 3 |

### Sync outputs

Eight, matching the enclosure. Chosen so they sit as two contiguous
runs of four on the pin header **and** on only two AVR ports, so the
ISR drives them with two register writes (~0.13 µs) rather than eight
`digitalWrite()` calls (~35 µs, a real skew between channels).

**Pro Micro** — right header, rows 4–11:

| Header | Pins | Port |
|---|---|---|
| A | `21`, `20`, `19`, `18` | PORTF |
| B | `15`, `14`, `16`, `10` | PORTB |

> **A3–A0 are the JTAG pins** (PF4–PF7). The firmware clears JTD in
> `MCUCR` at startup to release them as GPIO. Without that the port
> write is ignored and four channels never toggle — silently, with
> a clean compile and a correct-looking config.

**Leonardo**: `0`, `1`, `4`, `6`, `8`, `10`, `11`, `12`

The Leonardo cannot match the Pro Micro layout: its A0–A5 block is
six contiguous PORTF pins, not eight, so this set keeps the
two-port property and gives up one contiguous run.

Wire each output plus GND to a BNC connector.

### Reserved pins

| Pin | Function | Configuration |
|---|---|---|
| 2 | TRIG IN | `INPUT_PULLUP`, external interrupt capable |
| 3 | FREE/TRIG mode switch | `INPUT_PULLUP` |

| 9 | Event channel output | driven independently of the train |

These are excluded from the sync output set: the trigger pins when
`TRIG_FEATURE` is 1, and the event pin when `EVENT_CHANNEL_ENABLED` is 1.
The `sync_pulse_freerun` build sets it to 0, has no trigger path, and
uses both as additional outputs.

### Pins with a second function

| Pin | Also | Consequence |
|---|---|---|
| 0, 1 | `Serial1` hardware UART | Free to use as outputs: USB is a separate peripheral on the 32U4 and consumes no pins. Reclaim these two if a UART peripheral is ever added. |
| 13 | Onboard LED (Leonardo) | The LED mirrors the sync signal. |
| 2, 3 | INT0/INT1 | The only interrupt-capable pins broken out on a Pro Micro, which is why TRIG IN uses one. |

## 3. Panel connectors

| Connector | Direction | Signal |
|---|---|---|
| OUTPUTS 1-8 (BNC) | out | 0/5 V sync waveform, all identical |
| TRIG IN (BNC) | in | rising edge or level, per trigger mode |
| FREE/TRIG (SPDT) | in | run mode select |
| PWR (barrel) | in | DC input |
| GND (10-32 screw) | — | chassis / tether point |

### TRIG IN

BNC centre through a ~1 kΩ series resistor to the input pin, which is
`INPUT_PULLUP`. An idle master holding 0 V arms the input; it must sit
LOW for `TRIG_ARM_LOW_MS` = 20 ms before
a rising edge counts, so an unconnected jack cannot false-trigger.

### Mode switch

Common to the mode pin; the **FREE RUN throw leaves the pin OPEN** and
the TRIG RUN throw closes it to GND.

This polarity is deliberate. The pin is `INPUT_PULLUP`, so an unwired
or disconnected switch floats HIGH and reads FREE RUN — the box emits.
A switch that fails open fails into working. The opposite convention
leaves the box silent and waiting for a trigger that never arrives,
which is only discovered later, in analysis, when nothing aligns.

## 4. Signal

| Parameter | Default | Define |
|---|---|---|
| HIGH duration | 50–500 ms | `DEFAULT_M{IN,AX}_HIGH_MS` |
| LOW duration | 50–500 ms | `DEFAULT_M{IN,AX}_LOW_MS` |
| Duration quantum | 5 ms | the finest step the generator emits |
| PRNG seed | 42 | `DEFAULT_PRNG_SEED` |

Durations are drawn by a xorshift32 PRNG. **The waveform is fully
determined by (seed, configuration)**, so it can be regenerated offline
and used as ground truth — which is what the analysis toolkit does.

### Timecode frames

Every `DEFAULT_TC_INTERVAL_S` = 10 s the
train is interrupted by one frame carrying:

    [16-bit run ID][32-bit elapsed seconds][4-bit checksum]

| Element | Value | Define |
|---|---|---|
| Pulse width | 5 ms | `TC_PULSE_MS` |
| Preamble | 3 pulses, 10 ms gaps | `TC_PREAMBLE_GAP_MS` |
| Bit = 0 | 15 ms gap | `TC_GAP_ZERO_MS` |
| Bit = 1 | 25 ms gap | `TC_GAP_ONE_MS` |
| Lead-in | 20 ms forced LOW | `TC_LEADIN_MS` |

The run ID is an EEPROM counter incremented on every PRNG restart, so
(run ID, elapsed) identifies every moment the box has ever emitted,
across power cycles. Frames start exactly on the interval tick: a
decoded frame's first edge marks exactly `elapsed` seconds of generator
time, which gives absolute position with no pattern search.

Frames consume no PRNG draws, so the hybrid signal remains fully
reproducible.

**Reserved-gap rule**: keep minimum HIGH + minimum LOW well above
`TC_PULSE_MS` + `TC_GAP_ONE_MS` (100 vs 30 ms by
default) so the random section can never imitate frame timing.

## 5. Trigger modes

Runtime-settable, so one firmware serves several experimental designs
and a host application can change behaviour over serial.

| Mode | `trigmode` | Behaviour |
|---|---|---|
| `TRIG_MODE_EDGE_START` | `start` | A rising edge starts a run; further edges ignored until the mode switch is cycled. |
| `TRIG_MODE_EDGE_TOGGLE` | `toggle` | Rising edge starts, next edge stops, and so on. |
| `TRIG_MODE_LEVEL_GATE` | `gate` | Runs while TRIG IN is HIGH. The run clock restarts on each rising edge, so every gated segment is its own run with its own ID. |

### Lead-in marker

Optionally emit one clean pulse, hold LOW for a fixed pause, then begin
the train. A single unambiguous flash is far easier to find in video
than a pseudo-random train, so a camera recording an LED can be aligned
off that one event without decoding anything.

| Parameter | Default | Define |
|---|---|---|
| Enabled | off | `DEFAULT_LEADIN_PULSE_ENABLED` |
| Pulse width | 50 ms | `DEFAULT_LEADIN_PULSE_MS` |
| Pause | 500 ms | `DEFAULT_LEADIN_PAUSE_MS` |

The run clock starts at the **leading edge of the marker pulse**, so
embedded timecode stays referenced to the trigger instant, and the
pause is a known constant.

## 6. Event channel (pin 9)

Carries events instead of the sync train. Every trigger arriving on
TRIG IN emits a marker here; the remaining outputs carry the train
untouched.

    [MARK][gap][payload symbols, MSB first][gap]

| Element | Duration |
|---|---|
| MARK (the event) | 200 ms |
| Gap between symbols | 50 ms |
| Symbol = 0 | 50 ms |
| Symbol = 1 | 100 ms |
| Payload | 8-bit per-run event counter |
| Total marker | 1050–1450 ms |

**The MARK's leading edge is the event**, at interrupt latency
(~4 µs). Everything after it is an identifier and does not affect
timing, so accuracy is the same regardless of the payload.

The counter is per-run: event 3 of run 7 is unambiguous. It lets a
camera that saw only this channel tell one trigger from another,
which is the one thing a plain event flag cannot do.

**Close-spaced triggers**: a new trigger aborts a marker still in
progress. The MARK always fires; the counter is best-effort. Event
timing is never sacrificed to finish an identifier, and a decoder
reports the truncated marker with its exact timestamp rather than
guessing a number from partial bits.

Widths are sized for the slowest recorder that might see this: at
24 fps a frame is 41.7 ms, and a pulse must exceed one full frame
interval to be caught regardless of phase. The 200 ms mark spans
4.8 frames; the symbols span 1.2 and 2.4.

Decode with `presync.decode_events()`.

## 7. Serial interface

USB CDC (`Serial`), which consumes no GPIO. Commands are newline
terminated. Changes take effect immediately; `save` persists them.

| Command | Effect |
|---|---|
| `high <min> <max>` | HIGH duration range, ms |
| `low <min> <max>` | LOW duration range, ms |
| `seed <n>` | PRNG seed; same seed = same sequence |
| `tc on|off` | embedded timecode frames |
| `tcint <s>` | seconds between frames (min 2) |
| `trigmode start|toggle|gate` | what TRIG IN does |
| `mark on|off` | lead-in marker pulse before the train |
| `markms <pulse> <pause>` | marker width and LOW hold, ms |
| `save` | persist current config to EEPROM |
| `reset` | restore compile-time defaults |
| `start` | begin emitting |
| `stop` | stop emitting (outputs LOW) |
| `restart` | restart the PRNG; increments run ID |
| `pintest` |  |
| `config` | print the running configuration |
| `help` | list commands |

## 8. Persistence

| Item | Address | Notes |
|---|---|---|
| Config block | 0 | validated by magic byte `0xA9` |
| Run ID counter | 64 | separate, so `save` never touches it; wraps at 65535 |

Changing `EEPROM_MAGIC` forces a reset to compile-time defaults on the
next boot.

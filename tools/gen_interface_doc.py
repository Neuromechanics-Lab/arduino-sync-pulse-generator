#!/usr/bin/env python3
"""
gen_interface_doc.py - build docs/INTERFACE.md from the firmware sources.

The pin assignments, timing defaults and serial commands all live in
config.h and sync_pulse_generator.ino. Writing them out a second time by
hand guarantees the document and the device disagree eventually, so this
reads the sources and regenerates the document instead.

    python3 tools/gen_interface_doc.py

Run it after changing config.h or the command parser.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "sync_pulse_generator" / "config.h"
INO = ROOT / "sync_pulse_generator" / "sync_pulse_generator.ino"
OUT = ROOT / "docs" / "INTERFACE.md"


def defines(text):
    d = {}
    for m in re.finditer(r"^#define\s+(\w+)\s+(.+?)\s*(?://.*)?$",
                         text, re.M):
        d[m.group(1)] = m.group(2).strip()
    return d


def pin_arrays(text):
    """Both board variants' output pin lists, in declaration order."""
    out = []
    for m in re.finditer(r"const int OUTPUT_PINS\[\]\s*=\s*\{([^}]*)\}", text):
        out.append([p.strip() for p in m.group(1).split(",")])
    return out


def panel_pins(cfg):
    """The eight pins actually driven, per board.

    These come from PANEL_PINS, not from OUTPUT_PINS. The old array is the
    full set of GPIO the firmware once swept; the panel set is what the ISR
    port-writes and what the enclosure exposes, and reporting the former
    listed channels that do not exist.
    """
    out = {}
    for m in re.finditer(
            r"#define\s+PANEL_PINS\s+\{([^}]*)\}", cfg):
        pins = [p.strip() for p in m.group(1).split(",")]
        out[len(out)] = pins
    return out


def commands(text):
    """Serial command tokens, in the order the parser tests them."""
    seen, out = set(), []
    for m in re.finditer(r'strcmp\(token,\s*"([a-z]+)"\)\s*==\s*0', text):
        c = m.group(1)
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


CMD_HELP = {
    "high":     ("high <min> <max>",   "HIGH duration range, ms"),
    "low":      ("low <min> <max>",    "LOW duration range, ms"),
    "seed":     ("seed <n>",           "PRNG seed; same seed = same sequence"),
    "tc":       ("tc on|off",          "embedded timecode frames"),
    "tcint":    ("tcint <s>",          "seconds between frames (min 2)"),
    "trigmode": ("trigmode start|toggle|gate", "what TRIG IN does"),
    "mark":     ("mark on|off",        "lead-in marker pulse before the train"),
    "markms":   ("markms <pulse> <pause>", "marker width and LOW hold, ms"),
    "save":     ("save",               "persist current config to EEPROM"),
    "reset":    ("reset",              "restore compile-time defaults"),
    "start":    ("start",              "begin emitting"),
    "stop":     ("stop",               "stop emitting (outputs LOW)"),
    "restart":  ("restart",            "restart the PRNG; increments run ID"),
    "config":   ("config",             "print the running configuration"),
    "help":     ("help",               "list commands"),
}


def main():
    cfg = CONFIG.read_text()
    ino = INO.read_text()
    D = defines(cfg)
    arrays = pin_arrays(ino)
    pro, leo = (arrays + [[], []])[:2]
    panels = panel_pins(cfg)
    panel_pro = panels.get(0, [])
    panel_leo = panels.get(1, [])
    cmds = commands(ino)

    trig_in = D.get("TRIG_IN_PIN", "2")
    mode_sw = D.get("MODE_SWITCH_PIN", "3")
    ev_on = D.get("EVENT_CHANNEL_ENABLED", "0") == "1"
    ev_pin = D.get("EVENT_CHANNEL_PIN", "9")
    reserved = {trig_in, mode_sw} | ({ev_pin} if ev_on else set())

    def outputs(pins):
        return [p for p in pins if p not in reserved]

    L = []
    A = L.append
    A("# PRE-Sync — Interface Control Document")
    A("")
    A("Connector pinout, signal levels and the serial command set.")
    A("")
    A("**Generated from the firmware sources — do not edit by hand.**")
    A("Regenerate with `python3 tools/gen_interface_doc.py` after changing")
    A("`config.h` or the command parser.")
    A("")
    A("## 1. Electrical")
    A("")
    A("| Property | Value | Notes |")
    A("|---|---|---|")
    A("| Logic family | 5 V CMOS | ATmega32U4, hardware fixed |")
    A("| Output HIGH | 5.0 V nominal | |")
    A("| Output LOW | 0.0 V nominal | |")
    A("| Max current per pin | 40 mA absolute, **20 mA recommended** | "
      "ATmega32U4 datasheet |")
    A("| Max total across all pins | 200 mA | package limit, not per-pin sum |")
    A("| Output impedance | series resistor per channel | "
      "sized at build; see BOM |")
    A("")
    A("> **3.3 V equipment**: these outputs are 5 V. Use a divider or level")
    A("> shifter. Equipment with TTL inputs (HIGH above 2.4 V) accepts 5 V")
    A("> directly.")
    A("")
    A("> **Every output carries the same signal simultaneously.** Each has its")
    A("> own driver pin, so loading or shorting one channel does not disturb")
    A("> the others.")
    A("")
    A("## 2. Pin assignment")
    A("")
    A(f"Two board variants. Select Pro Micro with `-DBOARD_PRO_MICRO`.")
    A("")
    A("| Board | Panel outputs | Event channel | Reserved inputs |")
    A("|---|---|---|---|")
    ev = f"{ev_pin}" if ev_on else "—"
    A(f"| Arduino Leonardo | {len(panel_leo)} | {ev} | {trig_in}, {mode_sw} |")
    A(f"| Pro Micro ATmega32U4 | {len(panel_pro)} | {ev} | "
      f"{trig_in}, {mode_sw} |")
    A("")
    A("### Sync outputs")
    A("")
    A("Eight, matching the enclosure. Chosen so they sit as two contiguous")
    A("runs of four on the pin header **and** on only two AVR ports, so the")
    A("ISR drives them with two register writes (~0.13 µs) rather than eight")
    A("`digitalWrite()` calls (~35 µs, a real skew between channels).")
    A("")
    if panel_pro:
        A(f"**Pro Micro** — right header, rows 4–11:")
        A("")
        A(f"| Header | Pins | Port |")
        A(f"|---|---|---|")
        A(f"| A | `{'`, `'.join(panel_pro[:4])}` | PORTF |")
        A(f"| B | `{'`, `'.join(panel_pro[4:])}` | PORTB |")
        A("")
        A("> **A3–A0 are the JTAG pins** (PF4–PF7). The firmware clears JTD in")
        A("> `MCUCR` at startup to release them as GPIO. Without that the port")
        A("> write is ignored and four channels never toggle — silently, with")
        A("> a clean compile and a correct-looking config.")
        A("")
    if panel_leo:
        A(f"**Leonardo**: `" + "`, `".join(panel_leo) + "`")
        A("")
        A("The Leonardo cannot match the Pro Micro layout: its A0–A5 block is")
        A("six contiguous PORTF pins, not eight, so this set keeps the")
        A("two-port property and gives up one contiguous run.")
        A("")
    A("Wire each output plus GND to a BNC connector.")
    A("")
    A("### Reserved pins")
    A("")
    A("| Pin | Function | Configuration |")
    A("|---|---|---|")
    A(f"| {trig_in} | TRIG IN | `INPUT_PULLUP`, external interrupt capable |")
    A(f"| {mode_sw} | FREE/TRIG mode switch | `INPUT_PULLUP` |")
    A("")
    if ev_on:
        A(f"| {ev_pin} | Event channel output | driven independently of the "
          f"train |")
    A("")
    A("These are excluded from the sync output set: the trigger pins when")
    A("`TRIG_FEATURE` is 1, and the event pin when `EVENT_CHANNEL_ENABLED` is 1.")
    A("The `sync_pulse_freerun` build sets it to 0, has no trigger path, and")
    A("uses both as additional outputs.")
    A("")
    A("### Pins with a second function")
    A("")
    A("| Pin | Also | Consequence |")
    A("|---|---|---|")
    A("| 0, 1 | `Serial1` hardware UART | Free to use as outputs: USB is a "
      "separate peripheral on the 32U4 and consumes no pins. Reclaim these "
      "two if a UART peripheral is ever added. |")
    A("| 13 | Onboard LED (Leonardo) | The LED mirrors the sync signal. |")
    A(f"| {trig_in}, {mode_sw} | INT0/INT1 | The only interrupt-capable pins "
      "broken out on a Pro Micro, which is why TRIG IN uses one. |")
    A("")
    A("## 3. Panel connectors")
    A("")
    A("| Connector | Direction | Signal |")
    A("|---|---|---|")
    A("| OUTPUTS 1-8 (BNC) | out | 0/5 V sync waveform, all identical |")
    A("| TRIG IN (BNC) | in | rising edge or level, per trigger mode |")
    A("| FREE/TRIG (SPDT) | in | run mode select |")
    A("| PWR (barrel) | in | DC input |")
    A("| GND (10-32 screw) | — | chassis / tether point |")
    A("")
    A("### TRIG IN")
    A("")
    A("BNC centre through a ~1 kΩ series resistor to the input pin, which is")
    A("`INPUT_PULLUP`. An idle master holding 0 V arms the input; it must sit")
    A(f"LOW for `TRIG_ARM_LOW_MS` = {D.get('TRIG_ARM_LOW_MS','20')} ms before")
    A("a rising edge counts, so an unconnected jack cannot false-trigger.")
    A("")
    A("### Mode switch")
    A("")
    A("Common to the mode pin; the **FREE RUN throw leaves the pin OPEN** and")
    A("the TRIG RUN throw closes it to GND.")
    A("")
    A("This polarity is deliberate. The pin is `INPUT_PULLUP`, so an unwired")
    A("or disconnected switch floats HIGH and reads FREE RUN — the box emits.")
    A("A switch that fails open fails into working. The opposite convention")
    A("leaves the box silent and waiting for a trigger that never arrives,")
    A("which is only discovered later, in analysis, when nothing aligns.")
    A("")
    A("## 4. Signal")
    A("")
    A("| Parameter | Default | Define |")
    A("|---|---|---|")
    A(f"| HIGH duration | {D.get('DEFAULT_MIN_HIGH_MS')}–"
      f"{D.get('DEFAULT_MAX_HIGH_MS')} ms | `DEFAULT_M{{IN,AX}}_HIGH_MS` |")
    A(f"| LOW duration | {D.get('DEFAULT_MIN_LOW_MS')}–"
      f"{D.get('DEFAULT_MAX_LOW_MS')} ms | `DEFAULT_M{{IN,AX}}_LOW_MS` |")
    A(f"| Duration quantum | 5 ms | the finest step the generator emits |")
    A(f"| PRNG seed | {D.get('DEFAULT_PRNG_SEED')} | `DEFAULT_PRNG_SEED` |")
    A("")
    A("Durations are drawn by a xorshift32 PRNG. **The waveform is fully")
    A("determined by (seed, configuration)**, so it can be regenerated offline")
    A("and used as ground truth — which is what the analysis toolkit does.")
    A("")
    A("### Timecode frames")
    A("")
    A(f"Every `DEFAULT_TC_INTERVAL_S` = {D.get('DEFAULT_TC_INTERVAL_S')} s the")
    A("train is interrupted by one frame carrying:")
    A("")
    A("    [16-bit run ID][32-bit elapsed seconds][4-bit checksum]")
    A("")
    A("| Element | Value | Define |")
    A("|---|---|---|")
    A(f"| Pulse width | {D.get('TC_PULSE_MS')} ms | `TC_PULSE_MS` |")
    A(f"| Preamble | 3 pulses, {D.get('TC_PREAMBLE_GAP_MS')} ms gaps | "
      "`TC_PREAMBLE_GAP_MS` |")
    A(f"| Bit = 0 | {D.get('TC_GAP_ZERO_MS')} ms gap | `TC_GAP_ZERO_MS` |")
    A(f"| Bit = 1 | {D.get('TC_GAP_ONE_MS')} ms gap | `TC_GAP_ONE_MS` |")
    A(f"| Lead-in | {D.get('TC_LEADIN_MS')} ms forced LOW | `TC_LEADIN_MS` |")
    A("")
    A("The run ID is an EEPROM counter incremented on every PRNG restart, so")
    A("(run ID, elapsed) identifies every moment the box has ever emitted,")
    A("across power cycles. Frames start exactly on the interval tick: a")
    A("decoded frame's first edge marks exactly `elapsed` seconds of generator")
    A("time, which gives absolute position with no pattern search.")
    A("")
    A("Frames consume no PRNG draws, so the hybrid signal remains fully")
    A("reproducible.")
    A("")
    A("**Reserved-gap rule**: keep minimum HIGH + minimum LOW well above")
    A(f"`TC_PULSE_MS` + `TC_GAP_ONE_MS` "
      f"({int(D.get('DEFAULT_MIN_HIGH_MS',50)) + int(D.get('DEFAULT_MIN_LOW_MS',50))}"
      f" vs {int(D.get('TC_PULSE_MS',5)) + int(D.get('TC_GAP_ONE_MS',25))} ms by")
    A("default) so the random section can never imitate frame timing.")
    A("")
    A("## 5. Trigger modes")
    A("")
    A("Runtime-settable, so one firmware serves several experimental designs")
    A("and a host application can change behaviour over serial.")
    A("")
    A("| Mode | `trigmode` | Behaviour |")
    A("|---|---|---|")
    A("| `TRIG_MODE_EDGE_START` | `start` | A rising edge starts a run; "
      "further edges ignored until the mode switch is cycled. |")
    A("| `TRIG_MODE_EDGE_TOGGLE` | `toggle` | Rising edge starts, next edge "
      "stops, and so on. |")
    A("| `TRIG_MODE_LEVEL_GATE` | `gate` | Runs while TRIG IN is HIGH. The "
      "run clock restarts on each rising edge, so every gated segment is its "
      "own run with its own ID. |")
    A("")
    A("### Lead-in marker")
    A("")
    A("Optionally emit one clean pulse, hold LOW for a fixed pause, then begin")
    A("the train. A single unambiguous flash is far easier to find in video")
    A("than a pseudo-random train, so a camera recording an LED can be aligned")
    A("off that one event without decoding anything.")
    A("")
    A("| Parameter | Default | Define |")
    A("|---|---|---|")
    A(f"| Enabled | {'on' if D.get('DEFAULT_LEADIN_PULSE_ENABLED')=='1' else 'off'} "
      f"| `DEFAULT_LEADIN_PULSE_ENABLED` |")
    A(f"| Pulse width | {D.get('DEFAULT_LEADIN_PULSE_MS')} ms | "
      "`DEFAULT_LEADIN_PULSE_MS` |")
    A(f"| Pause | {D.get('DEFAULT_LEADIN_PAUSE_MS')} ms | "
      "`DEFAULT_LEADIN_PAUSE_MS` |")
    A("")
    A("The run clock starts at the **leading edge of the marker pulse**, so")
    A("embedded timecode stays referenced to the trigger instant, and the")
    A("pause is a known constant.")
    A("")
    if ev_on:
        mark = int(D.get("EVENT_MARK_MS", 200))
        gap = int(D.get("EVENT_GAP_MS", 50))
        b0 = int(D.get("EVENT_BIT0_MS", 50))
        b1 = int(D.get("EVENT_BIT1_MS", 100))
        nb = int(D.get("EVENT_COUNTER_BITS", 8))
        lo = mark + gap + nb * (b0 + gap)
        hi = mark + gap + nb * (b1 + gap)
        A(f"## 6. Event channel (pin {ev_pin})")
        A("")
        A("Carries events instead of the sync train. Every trigger arriving on")
        A("TRIG IN emits a marker here; the remaining outputs carry the train")
        A("untouched.")
        A("")
        A("    [MARK][gap][payload symbols, MSB first][gap]")
        A("")
        A("| Element | Duration |")
        A("|---|---|")
        A(f"| MARK (the event) | {mark} ms |")
        A(f"| Gap between symbols | {gap} ms |")
        A(f"| Symbol = 0 | {b0} ms |")
        A(f"| Symbol = 1 | {b1} ms |")
        A(f"| Payload | {nb}-bit per-run event counter |")
        A(f"| Total marker | {lo}–{hi} ms |")
        A("")
        A("**The MARK's leading edge is the event**, at interrupt latency")
        A("(~4 µs). Everything after it is an identifier and does not affect")
        A("timing, so accuracy is the same regardless of the payload.")
        A("")
        A("The counter is per-run: event 3 of run 7 is unambiguous. It lets a")
        A("camera that saw only this channel tell one trigger from another,")
        A("which is the one thing a plain event flag cannot do.")
        A("")
        A("**Close-spaced triggers**: a new trigger aborts a marker still in")
        A("progress. The MARK always fires; the counter is best-effort. Event")
        A("timing is never sacrificed to finish an identifier, and a decoder")
        A("reports the truncated marker with its exact timestamp rather than")
        A("guessing a number from partial bits.")
        A("")
        A("Widths are sized for the slowest recorder that might see this: at")
        A("24 fps a frame is 41.7 ms, and a pulse must exceed one full frame")
        A(f"interval to be caught regardless of phase. The {mark} ms mark spans")
        A(f"{mark/41.67:.1f} frames; the symbols span {b0/41.67:.1f} and "
          f"{b1/41.67:.1f}.")
        A("")
        A("Decode with `presync.decode_events()`.")
        A("")
    A("## 7. Serial interface" if ev_on else "## 6. Serial interface")
    A("")
    A("USB CDC (`Serial`), which consumes no GPIO. Commands are newline")
    A("terminated. Changes take effect immediately; `save` persists them.")
    A("")
    A("| Command | Effect |")
    A("|---|---|")
    for c in cmds:
        usage, desc = CMD_HELP.get(c, (c, ""))
        A(f"| `{usage}` | {desc} |")
    A("")
    A("## 8. Persistence" if ev_on else "## 7. Persistence")
    A("")
    A("| Item | Address | Notes |")
    A("|---|---|---|")
    A(f"| Config block | 0 | validated by magic byte "
      f"`{D.get('EEPROM_MAGIC')}` |")
    A(f"| Run ID counter | {D.get('EEPROM_RUNID_ADDR')} | separate, so `save` "
      "never touches it; wraps at 65535 |")
    A("")
    A("Changing `EEPROM_MAGIC` forces a reset to compile-time defaults on the")
    A("next boot.")
    A("")

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("\n".join(L))
    print(f"wrote {OUT.relative_to(ROOT)}  "
          f"({len(L)} lines, {len(outputs(leo))}/{len(outputs(pro))} outputs, "
          f"{len(cmds)} commands)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

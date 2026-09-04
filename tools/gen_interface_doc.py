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
    cmds = commands(ino)

    trig_in = D.get("TRIG_IN_PIN", "2")
    mode_sw = D.get("MODE_SWITCH_PIN", "3")
    reserved = {trig_in, mode_sw}

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
    A("| Board | Total GPIO | Sync outputs | Reserved inputs |")
    A("|---|---|---|---|")
    A(f"| Arduino Leonardo (default) | {len(leo)} | {len(outputs(leo))} | "
      f"{trig_in}, {mode_sw} |")
    A(f"| Pro Micro ATmega32U4 | {len(pro)} | {len(outputs(pro))} | "
      f"{trig_in}, {mode_sw} |")
    A("")
    A("### Sync outputs")
    A("")
    A(f"**Leonardo** ({len(outputs(leo))}): `" +
      "`, `".join(outputs(leo)) + "`")
    A("")
    A(f"**Pro Micro** ({len(outputs(pro))}): `" +
      "`, `".join(outputs(pro)) + "`")
    A("")
    A("Wire any output pin plus GND to a BNC connector.")
    A("")
    A("### Reserved pins")
    A("")
    A("| Pin | Function | Configuration |")
    A("|---|---|---|")
    A(f"| {trig_in} | TRIG IN | `INPUT_PULLUP`, external interrupt capable |")
    A(f"| {mode_sw} | FREE/TRIG mode switch | `INPUT_PULLUP` |")
    A("")
    A("These two are excluded from the output set when `TRIG_FEATURE` is 1.")
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
    A("## 6. Serial interface")
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
    A("## 7. Persistence")
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

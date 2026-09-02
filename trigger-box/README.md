# PRE-Sync — trigger box for sync_pulse_generator

3D-printed, copper-foil-lined enclosure for the Pro Micro (ATmega32U4 5V)
running [`../sync_pulse_generator`](../sync_pulse_generator). Eight BNC sync
outputs; TRIG input for chaining multiple boxes off one master signal.

**Three parts, no supports anywhere:** the **frame** (walls + corner posts,
open at both ends), the **face plate** (flat display plate, screws onto one
end with countersunk M3 self-tappers into the posts), and the **lid**
(screws onto the other end). Assembled ~174 × 51 × 37 mm, 3 mm walls.

**Faces:**
- **Front:** 8 BNC outputs at 19 mm pitch, numbered `1`–`8` left to right,
  `OUTPUTS` caption above. **Each jack is driven by its own Arduino pin**
  through a 220 Ω series resistor (all pins carry the identical signal), so
  every cable has a full 5 V driver behind it — no shared drivers, no pots.
  Level control per device, if needed, is an inline attenuator pod (idea
  logged, not built).
- **Rear:** `TRIG IN` BNC + SPDT mode toggle (`FREE RUN ⟷ TRIG RUN`, arrow
  from TRIG RUN to the IN jack) under a `CONTROL` caption.
- **Left end:** `PWR` barrel jack, centered.
- **Right end:** 10-32 thread-forming ground/tether screw, dead center —
  self-taps through the wall into the copper foil inside (the shield's single
  ground point), tether ring terminal under the head outside.
- **FACE PLATE (deployed top):** Neuromechanics Lab icon
  (`logo-icon-filled.svg` — outlines filled so every shape is a solid inset) + **PRE-Sync** wordmark as a 1.2 mm **inset whose floor
  is colored** — a 0.6 mm slab of filament 1 sits directly under the recess
  inside the body, so you look into the inset and see orange at the bottom,
  body color on the walls. **10 mm blue LED centered in the neuron's soma.**
- **Lid (deployed bottom):** 4 corner screws, two keyhole mounts (M4/#8
  heads; slots toward the front — hang and slide to lock), lab attribution
  inset inside.

**All lettering is inset** (0.8 mm deboss; walls in Futura Medium 4.6 mm with light stroke fattening
so the grooves print smooth).

## Top bracing and PCB mount

The bottom edge is closed by the lid and both ends by the face and lid screws,
but the top opening had nothing holding its long edges apart — 168 mm of
unsupported wall that could bow. Two things fix that:

- **A ledge** (`ledge_w` 2.5 mm × `ledge_h` 3 mm) runs the inside of the top
  rim, turning the free edge into a flange. A flange resists bending far better
  than the same mass added as wall thickness. It stops short of the corner posts
  so the face plate still seats on the posts.
- **Two cross beams** (`beam_w` 8 mm × `beam_h` 4 mm) span the short way, wall to
  wall, at the PCB post spacing. They close the load path between the long
  walls, so the walls can no longer splay.

**The board hangs from the beams**, horizontal, on four posts dropping from
their undersides (`pcb_hang` 4 mm, M2.5 self-tappers into `pcb_pilot` 2.2 mm).
This replaces the earlier scheme, where four posts stood off the rear wall and
the board mounted vertically on their ends.

Two things that buys:

- **Serviceable from both faces.** Take the logo face off (top) to reach the
  beams and the component side; take the lid off (bottom) to reach the solder
  side.
- **Out of the way of everything.** The board is centred at `pcb_cx` 34 /
  `pcb_cy` −11, so it spans x −4..72 and y −21..−1 — pulled back against the
  rear wall, leaving 23.5 mm clear in front for the eight BNC bulkhead bodies,
  and well clear in x of the face LED at x −51. It lands at z 20, 3 mm above the
  z 17 centreline of the BNC and barrel jacks.

> **`pcb_dx` (76) and `pcb_dy` (15) are still unverified.** `dx` carried over
> from the vertical scheme; `dy` is a guess at the hole spacing across the
> board's 20 mm dimension. Measure the real board before printing — four posts
> at the wrong pitch line up with nothing. Check them on `trigger-hole_test`
> along with the connector diameters.

## Printing

STLs only — slice in Bambu Studio yourself (never a command-line slice; the
CLI can't resolve Bambu's filament profiles and produces 0 g / no-extrusion
files). `./export-parts.sh` regenerates `exports/stl/*.stl` after any change.
Every part prints flat exactly as exported — **no rotation, no supports.**

1. `trigger-hole_test` first (~10 min): every hole + keyhole + an inset label
   sample. VERIFY bnc/switch/barrel/led diameters against the real parts.
2. `trigger-frame` — walls only, either end down. Single color.
3. **Face plate, two-color:** import `trigger-face.stl` AND
   `trigger-face_art.stl` together → **Yes** to "load as a single object with
   multiple parts" → `trigger-face_art` (the recess-floor slab) → filament 1
   (orange), `trigger-face` → filament 2. Face up as exported. The color
   change is 3 layers just below the top surface. Check the sliced weight is
   a real number before printing.
4. `trigger-lid` flat as-is, single color.

Assembly: 4 × M3 self-tappers through the face plate's countersinks into the
posts (either in-plane rotation of the plate works — pick the one where the
wordmark reads the way you want relative to the OUTPUTS wall), 4 more
through the lid. LED holder nut goes on inside the plate before it's screwed
down.

## Copper foil shielding

Line the interior with conductive-adhesive copper tape: overlap seams,
ground the foil to circuit GND at exactly ONE point (the ground screw), keep
it clear of the Pro Micro's underside. BNC shells touching the foil is fine
(shield = GND).

## Electrical notes

- Outputs: 8 pins (Pro Micro: 4, 5, 6, 7, 8, 9, 10, 14) → 220 Ω → BNC
  center; all BNC shells to GND. Pins 2/3 are reserved by the firmware for
  TRIG IN / mode switch.
- SPDT toggle: MTS-102 style (6 mm bushing, 6.5 mm hole, fit-tested).
- TRIG IN → 1 kΩ series → pin 2; switch common → pin 3, FREE throw → GND.
  See the sync_pulse_generator README for the arming logic.

## Accessory pucks (`pods.scad`)

Round Ø60 pucks on a shared body, all parts flat, no supports. Each puck =
`base` (keyhole plate, common) + a ring + a top plate, 4 × M3 self-tappers
each end into the ring's posts. Hung by the keyhole, the top plate faces out
and the jacks run left–right. Exported as `exports/stl/pod-*.stl`.

| Puck | Ring | Top | Inside |
|---|---|---|---|
| **GAIN** (inline attenuator) | `pod-ring` — IN + OUT, 40 tall | `pod-top_gain` — pot, `GAIN`, arc arrow `LOW` → `HIGH` | IN center → pot end, wiper → OUT center, other end → shields. High-impedance loads only |
| **LED** | `pod-ring_in` — IN only, 28 tall | `pod-top_led` — Ø20 boss with a **1/4"-20 heat-set insert** for a hollow **gooseneck** (mic/lamp type: wires run inside, holds any position, never free-spins) | IN center → series resistor (~220 Ω for a 10 mm LED at 5 V) → up the gooseneck |
| | | `pod-led_head` — screws onto the gooseneck's far end: insert in the bottom, 10 mm LED press-fit + 14 mm ring seat on top, wires through the middle | |
| **SOUND** | `pod-ring_in` | `pod-top_sound` — pocket for a 23 mm **5 V active piezo buzzer**, grille, `VOL` pot, `LEVEL`/`EDGE` toggle | see below |

**SOUND puck circuit** — buzzer + ← VOL pot (series, volume) ← IN center.
The SPDT toggle sits on the buzzer's − side and picks how it reaches the
shield (ground):

- `LEVEL`: buzzer − → shield directly. Sounds for the whole HIGH.
- `EDGE`: buzzer − → NPN collector (2N3904 / BC547), emitter → shield. Base
  ← 22 kΩ ← 1 µF ← IN center, with 10 kΩ base→shield and a 1N4148 from
  shield to base (cathode at base) to clamp the falling-edge spike. The
  capacitor passes only the rising edge, so the transistor conducts for
  ≈ RC ≈ 20 ms: one blip per rising edge, powered by the line itself (every
  HIGH lasts ≥ 50 ms). Change 1 µF / 22 kΩ for a longer or shorter blip.

Parts to buy: 1/4"-20 heat-set brass inserts (two per LED puck — VERIFY the
OD against `gn_insert_d`), a 1/4"-20 gooseneck (6–12"), a 5 V active piezo
buzzer (VERIFY `buzzer_d`). Print `pod-top_led` boss-up and `pod-top_sound`
as exported (outside face on the bed, pocket walls growing up).

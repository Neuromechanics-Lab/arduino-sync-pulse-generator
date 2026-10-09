# PRE-Sync — six-output trigger box

A variant of [`../trigger-box`](../trigger-box): the same 174 × 51 × 37 mm box
and the same face plate, with six BNC outputs, no power jack, and the Pro
Micro's own USB-C socket showing through the end wall. Everything not
described here (labels, face art, copper foil, keyholes, the electrical notes)
is as in the eight-output README.

**Status, 2026-10-09: drawn, not printed.** Every part renders manifold and the
interference checks below pass, but nothing has been fitted in plastic. Print
`fit_test` first.

## What changed, and why

| | eight-output box | this box |
|---|---|---|
| Outputs | 8 BNC | **6 BNC**, in the positions of the old outputs 3–8, numbered 1–6 |
| Power | barrel jack, left end | **none** — USB-C opening in its place, dead centre in the end wall |
| Board | perfboard hung from two beams | Pro Micro in a **separate cradle**, glued onto four pillars |
| Plate screws | M3 self-tappers into the posts | **M3 machine screws into captive hex nuts**, both plates |
| TRIG IN + toggle | left half of the rear wall | **centre of the rear wall** |
| Ground screw | right end | unchanged |

- **Which two outputs went.** The eight-slot grid is kept and the two slots
  nearest the USB end are not cut, so the board has about 45 mm of front wall
  with no BNC body behind it.
- **Why the rear controls moved.** They sat in the half of the box that now
  holds the board. The toggle's body comes in from the rear wall at the same
  height as the board and would have met it.
- **Why the fourth pillar pair hangs from wall lugs, not a beam.** The face LED
  comes through the plate 51 mm left of centre, between those two pillars. A
  full beam there would sit on it.

## The USB end: notch and opening

The socket's metal shell comes through the end wall and ends **flush with the
outside face**. The opening is the shell plus 0.25 mm clearance a side
(9.5 × 3.7 mm), no larger; the cable's plug body stays outside.

To get the socket that far out, the inside of the wall has a pocket the width
of the board, and the board's end sits in it. The pocket's depth is the wall
(3 mm) less the socket's overhang past the board edge, so the skin left
beyond it is exactly as thick as the overhang. With the measured 2 mm overhang
that is a 1 mm pocket and a 2 mm skin.

`usb_over` decides whether the socket ends up flush: too small a figure
leaves it proud of the wall, too large leaves it shy.
The cradle's base sits flush against the wall; the board overhangs it into the
pocket.

## The cradle

A flat base the board lies on, corner ribs 1.2 mm thick with 0.3 mm clearance,
and the wall end open so the socket reaches the opening. Two straps carry four
blind sockets on the opposite face from the ribs; they drop over the pillar
ends, so the cradle locates itself.

Print it in **ASA**, socket face on the bed, ribs up. Silicone the board into
it; superglue the sockets onto the pillars.

The board is on the lid side of the cradle, components toward the lid. With the
frame rim-down on the bench and the lid off, the cradle sits on the pillars and
the board sits on top of it, right way up and reachable. Deployed face-up the
board is underneath the cradle, held by the silicone and the ribs.

The cradle's underside is 9.9 mm behind the face plate, directly over the face
LED. That is the room the LED's back and its bent leads have.

## Captive nuts

Each corner post is a 10 mm block with, at each end, a clearance hole down its
axis and a slot in its side 3.5 mm in. The slot opens toward the middle of the
box. Slide an M3 hex nut in until it is under the hole, then a drop of
superglue at the slot mouth. Eight nuts.

Screws: **M3 × 10 countersunk**, eight (3 mm plate + 3.5 mm + 2.4 mm nut).

The lid's lip has larger corner notches for these posts, and the inside
attribution text is gone (it did not show on the print). **The eight-output
lid does not fit this frame.** The face plate is the same part.

## Not measured — check on `fit_test`

| parameter | value | source |
|---|---|---|
| `brd_w` | 19 mm | measured by hand, 2026-10-09 |
| `brd_l` (sets the back ribs) | 36.3 mm | from a fit: the first print's back ribs moved 4 mm toward the wall (3 mm of give found, plus the 1 mm notch), then eased back 0.3 mm |
| `brd_t` | 1.6 mm | nominal |
| `usb_over` (socket past the board edge) | 2.0 mm | measured by hand, 2026-10-09 |
| `usb_shell_h` | 3.2 mm | nominal |
| `usb_shell_w` | 9.0 mm | nominal USB-C receptacle |
| `nut_af`, `nut_t` | 5.5, 2.4 mm | nominal M3 hex |

`usb_shell_h` and `brd_t` set the height the board sits at, so a wrong value
puts the socket off-centre in the opening. Each is one number at the top of
the `.scad`.

## Printing

STLs only; slice by hand. `./export-parts.sh` writes `exports/stl/trigger6-*.stl`.

1. `trigger6-fit_test` — the USB end of the real frame, cut off just past the
   cradle and just above the pillar ends; print it **rim down** like the
   frame. It has all four pillars at their true spacing, the end wall with the
   USB opening and notch at their true height, and two corner posts with nut
   slots. Seat the cradle on the pillars, lay the board in it with its end in
   the notch, check the socket comes out flush, plug the cable in, and try a
   nut in each slot. (BNC, toggle and LED hole sizes are
   unchanged from the eight-output box, where they were fit-tested.)
2. `trigger6-cradle` — ASA, base down.
3. `trigger6-frame` — **rim down** (face end on the plate), no supports.
4. `trigger6-face` + `trigger6-face_art` — as the eight-output box.
5. `trigger6-lid` — flat.

## Assembly order

1. All eight nuts in and glued. The four at the face end are reached from the
   lid side and are hard to get at once the cradle is in.
2. Board into the cradle with silicone; let it set.
3. Cradle onto the pillars from the lid side, socket mouth against the end
   wall opening; superglue.
4. Panel hardware, wiring, foil, plates.

## Checked in the model

Intersection volumes, all zero: cradle–frame, board–frame, board–cradle, eight
nuts–frame, lid–frame, face plate–frame, and nominal envelopes for the toggle,
the seven BNC bodies and the LED against the frame, the cradle and the board.
The pillars (7.2 mm long) enter the cradle sockets by 1.3 mm. The LED envelope
used is Ø14 × 9 mm behind the face plate.

Not checked: anything that depends on a number in the table above.

## Open

- The wiring diagram, BOM and firmware pin list in `../docs` describe the
  eight-output box; outputs 7 and 8 are simply not wired here. The optional
  event channel is documented on output 8, which this box does not have.

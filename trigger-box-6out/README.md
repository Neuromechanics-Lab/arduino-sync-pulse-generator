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
| Board | perfboard hung from two beams | Pro Micro in a **separate cradle**, screwed onto four pillars |
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

To get the socket that far out, the inside of the wall has a slim slot the
width of the board and 2 mm tall, and the board's edge sits in it. The slot
holds the board's nose top and bottom; the socket shell rides above the board
and leaves through the opening, which the slot runs into. The slot's depth is
the wall (3 mm) less the socket's overhang past the board edge: with the
measured 2 mm overhang, a 1 mm slot and a 2 mm skin.

The 2 mm height assumes a 1.6 mm board (0.2 mm above and below). Board
thickness is not measured.

The cradle's base sits flush against the wall; the board overhangs it into the
slot.

## The cradle

A flat base the board lies on, corner ribs 1.2 mm thick with 0.3 mm clearance,
and the wall end open so the socket reaches the opening. Two straps reach out
to four pillars and sit flat on their ends.

**It is screwed on, not glued.** An M3 × 12 pan head goes in from the lid side,
through the strap, down the pillar and through the beam, into a hex nut
sitting in a pocket on the beam's outer (rim) face. The nut drops in from the
face side; tightening pulls it into the pocket floor, and the face plate then
covers it. So the cradle comes out again with four screws.

Print it in **ASA**, flat side on the bed, ribs up. Silicone the board into it.

The board is on the lid side of the cradle, components toward the lid. With the
frame rim-down on the bench and the lid off, the cradle sits on the pillars and
the board sits on top of it, right way up and reachable. Deployed face-up the
board is underneath the cradle, held by the silicone, the ribs and the wall
slot.

The cradle's underside is 9.9 mm behind the face plate, directly over the face
LED. That is the room the LED's back and its bent leads have.

## Captive nuts

Each corner post is a 10 mm block with, at each end, a clearance hole down its
axis and a slot in its side 3.5 mm in. The slot opens toward the middle of the
box. Slide an M3 hex nut in until it is under the hole, then a drop of
superglue at the slot mouth. Eight nuts for the plates, plus the four in the
beam pockets for the cradle: **twelve M3 hex nuts**.

Screws: **M3 × 10 countersunk**, eight, for the plates (3 mm plate + 3.5 mm +
2.4 mm nut); **M3 × 12 pan head**, four, for the cradle.

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
   cradle and 4 mm above the top of the USB opening; print it **rim down** like the
   frame. It has all four pillars at their true spacing, the end wall with the
   USB opening and slot at their true height, two corner posts with nut slots,
   and the four nut pockets. Screw the cradle to the pillars, put the board in
   nose first, check the socket comes out flush, plug the cable in, and try a
   nut in each slot and pocket. (BNC, toggle and LED hole sizes are
   unchanged from the eight-output box, where they were fit-tested.)
2. `trigger6-cradle` — ASA, base down.
3. `trigger6-frame` — **rim down** (face end on the plate), no supports.
4. `trigger6-face` + `trigger6-face_art` — as the eight-output box.
5. `trigger6-lid` — flat.

## Assembly order

1. The eight post nuts in and glued. The four at the face end are reached from
   the lid side and are hard to get at once the cradle is in.
2. Four nuts into the beam pockets from the face side (a drop of glue keeps
   them from falling out before the face plate is on).
3. Cradle onto the pillars from the lid side, flush against the end wall;
   four M3 × 12. **Without the board**: the board cannot come down with it,
   since its nose has to enter the wall sideways.
4. Silicone on the cradle. Board in nose first, tilted a few degrees: socket
   through the opening, board edge into the slot, then lower the tail between
   the back ribs.
5. Panel hardware, wiring, foil, plates.

## Checked in the model

Intersection volumes, all zero: cradle–frame, board–frame, board–cradle, eight
post nuts–frame, cradle screws and their nuts against frame, cradle, board and
bought parts, lid–frame, face plate–frame, and nominal envelopes for the toggle,
the seven BNC bodies and the LED against the frame, the cradle and the board.
The pillars are 5.9 mm long and the cradle's straps bear flat on their ends.
The LED envelope used is Ø14 × 9 mm behind the face plate.

Not checked: anything that depends on a number in the table above.

## Open

- The wiring diagram, BOM and firmware pin list in `../docs` describe the
  eight-output box; outputs 7 and 8 are simply not wired here. The optional
  event channel is documented on output 8, which this box does not have.

# PRE-Sync accessories

Small powered pods that adapt the box's outputs to recorders it cannot drive
directly. All are optional; the box is complete without them.

## Event fan-out pod (1→4)

**Purpose.** The event channel is a single BNC, and a session often needs the
same event delivered to several recorders at once — a camera, a DAQ, a
stimulus PC. Daisy-chaining from one output loads it unpredictably and the
edge degrades differently at each tap, which is exactly the kind of unknown
this system exists to remove.

**Function.** One BNC in, four buffered BNC out, all carrying the same signal.
Each output is independently driven, so loading or shorting one does not
disturb the others — the same guarantee the main box makes for its eight
channels, for the same reason.

**Why powered.** A passive splitter divides the signal and its edge rate
degrades with every branch. A buffered pod regenerates full-amplitude edges on
each output, so the fourth device sees the same rise time as the first. Skew
between outputs is then a fixed, measurable constant rather than a function of
what happens to be plugged in.

| Parameter | Target |
|---|---|
| Inputs | 1 × BNC |
| Outputs | 4 × BNC, independently buffered |
| Propagation delay | < 50 ns, matched across outputs |
| Output-to-output skew | < 10 ns (**TBM**) |
| Input impedance | high-Z, so it does not load the source |
| Supply | 5 V, barrel or USB |
| Logic | 5 V CMOS, matching the main box |

**Implementation note.** A single hex buffer (74HC541 or similar) covers this
with two gates spare. No microcontroller: the pod must not add timing
uncertainty of its own, and anything with firmware eventually has jitter.

**Skew must be measured, not assumed.** The propagation delay is common to all
four outputs and therefore harmless — it shifts every recorder equally. The
skew *between* outputs is not, because it appears as a fixed offset between
two recorders that no analysis can distinguish from a real one. Measure it
once per pod and record it on the unit.

## LED converter

**Purpose.** Makes a channel visible to cameras that have no electrical input.

Plugs into either the sync train (1–7) or the event channel (8), or two units
into both. On the event channel the 200 ms mark is unmistakable at 24 fps; on
the train, the 50–500 ms pulses are followed easily by any camera.

| Parameter | Target |
|---|---|
| Input | 1 × BNC, high-Z |
| Output | high-brightness LED, wide viewing angle |
| Turn-on delay | < 1 ms (**TBM**) |
| Supply | 5 V |

**Turn-on delay is a real offset**, not a rounding error: it appears between
the electrical signal and the optical one, so a session mixing cameras and
DAQs inherits it. Measure it and record it, the same as pod skew.

## Heat-set inserts

The gooseneck screws into a brass heat-set insert at each end — the LED puck
base and the LED head take the same one, so the gooseneck fits either way
round.

| | |
|---|---|
| Part | McMaster **151030**, `INS 29/250-20/.312L`, brass |
| Thread | 1/4"-20 |
| Insert OD | 0.290 in = **7.37 mm** |
| Insert length | 0.312 in = **7.92 mm** |
| Printed hole | **7.07 mm** (OD − 0.3) |
| Pocket depth | 9.5 mm |

**The hole is deliberately smaller than the insert.** A heat-set insert is
pressed in with a soldering iron: the plastic melts and flows into the
knurling, and that interference is what holds it. A hole at or above the
insert's OD gives the knurl nothing to bite, and the insert spins under the
first real torque — which, on a gooseneck, is every time it is repositioned.
0.3 mm under leaves 0.15 mm per side to melt: enough to grip, not enough to
split the boss.

### Installing

1. Fit a **soldering iron insert tip** if you have one; otherwise a
   conical tip works. Set **200–230 °C** for PETG, 180–200 °C for PLA.
   Too hot scorches and the insert sinks crooked; too cold and it stalls
   part-way and cannot be pushed further without tearing the boss.
2. Rest the insert on the hole. The printed pocket has a **0.8 mm lead-in
   chamfer** so it self-centres — start it square there rather than by eye.
3. Press down slowly and **check squareness from two directions** at the
   halfway point. A crooked insert cannot be straightened once it cools; it
   has to be melted back out and the boss is usually ruined.
4. Stop when the insert is **flush or 0.1–0.2 mm below** the surface. Proud
   inserts stop the gooseneck collar from seating flat.
5. Let it cool fully before threading anything in. Brass holds heat, and
   tapping a thread into softened plastic strips the grip you just made.

If an insert does spin later, the fix is a larger insert into a drilled-out
boss, not glue — adhesive on a rotating joint fails again under the same load.

## Status

All accessories are **specified, not built**. Targets marked **TBM** require a
built unit. See `docs/TEST_PROCEDURE.md` for the measurement method.

// ============================================================================
// trigger-box-6out.scad — PRE-Sync, six-output enclosure (32U4 Pro Micro)
//
// A variant of ../trigger-box/trigger-box.scad. Same outer box, same face
// plate. What differs:
//   * SIX BNC outputs, not eight. The two positions nearest the USB end are
//     left out so the board has the front wall to itself there.
//   * NO power jack. The Pro Micro is powered through its own USB-C socket,
//     which comes through the end wall where the barrel jack was and ends
//     flush with the outside. The board's end sits in a notch in that wall.
//   * The board sits in a separate CRADLE (print in ASA), siliconed in. The
//     cradle is SCREWED onto four pillars built against the long walls:
//     M3 x 8 through the cradle into a nut slid into the pillar's side.
//   * Plates are held by M3 MACHINE screws into hex nuts. Each corner post
//     has a side slot at each end; a nut slides in from inside the box and is
//     glued. Twelve nuts in all: four face plate, four lid, four cradle.
//   * FREE RUN ONLY. There is no TRIG IN jack and no mode toggle; the rear
//     wall is blank. (The firmware reads an unwired mode pin as free run.)
//
// PARTS (no supports anywhere):
//   frame     walls, nut posts, beams, pillars. Print RIM DOWN (face end on
//             the plate): beams are first layer, pillars grow up.
//   cradle    ASA. Flat side on the bed, ribs up.
//   face      unchanged from the eight-output box. Face UP; import face +
//             face_art into ONE Bambu Studio object (face_art -> filament 1).
//   lid       flat as-is. Corner notches in the lip are larger than the
//             eight-output lid's, so that lid does NOT fit this frame.
//   fit_test  print FIRST, rim down: the USB end of the frame cut short —
//             all four pillars, the USB opening, two nut posts.
//
//   openscad -o frame.stl -D 'part="frame"' trigger-box-6out.scad
//   (likewise cradle, face, face_art, lid, fit_test; "preview" to look)
// ============================================================================

include <lib/nyk-lib.scad>

part = "frame"; // "frame" | "cradle" | "face" | "face_art" | "lid" | "fit_test" | "preview"

// ---- Cavity -----------------------------------------------------------------
inner = [168, 45, 31];
wall  = 3;            // 3mm all walls (keyhole pads on the lid go thicker)
rad   = 3;

// ---- Panel hardware (VERIFY on fit_test) ------------------------------------
bnc_d     = 9.7;   // threaded bulkhead BNC, 3/8" barrel
led_d     = 10.4;  // bare 10mm LED pressed in from the inside; its flange
                   // sits against the plate interior (VERIFY on fit_test)
led_ring_d = 14;   // the LED's panel-mount ring (~11.5 measured) + a style margin:
                   // a circular INSET of this diameter around the hole, same
                   // depth as the art, so the ring sits in it near flush on
                   // the soma's orange floor (VERIFY on fit_test)
led_bezel_d = 0;   // 0 = no raised/flat landing (ring is inset instead)

// ---- Front row (+Y): 6 BNC outputs ------------------------------------------
// The eight-output box's grid (19mm pitch, eight slots centred on the wall) is
// kept, and the two slots nearest the USB end (-X) are simply not cut. So the
// six jacks sit exactly where outputs 3-8 sat, and are numbered 1-6. In the
// deployed (face-up) box, viewed from the front, output 1 is LEFT-most =
// smallest model x.
n_slots    = 8;                 // the grid
out_skip   = 2;                 // slots left out at the -X (USB) end
n_out      = n_slots - out_skip;
out_pitch  = 19;
front_z    = 17;
function out_x(i) = (i + out_skip - (n_slots - 1)/2) * out_pitch;   // i = 0..n_out-1
out_cx     = (out_x(0) + out_x(n_out - 1)) / 2;   // caption centres on the group

// ---- Rear (-Y): blank. This box free-runs; no TRIG input, no mode switch. ----

// ---- Left end (-X): USB-C opening, dead centre -------------------------------
// The socket's metal shell comes THROUGH the wall and ends flush with the
// outside face. The opening is the shell plus the printer fit clearance and
// nothing more; the cable's plug body stays outside.
usb_z      = 18.5;  // mid-height of the assembled box (same as the ground screw)
usb_shell_w = 9.0;  // socket shell width  (VERIFY — nominal USB-C receptacle)
usb_shell_h = 3.2;  // socket shell height above the board (VERIFY — nominal)

// ---- The board ---------------------------------------------------------------
// 19 wide, socket 2 past the board edge: measured by hand on 2026-10-09.
// Length is set from a fit, not a ruler. The first printed cradle had a 38
// pocket with the board edge 1 off the wall; with the board pushed hard to
// the wall there was 3 of give at the back ribs. The board now goes a
// further 1 into the wall notch, so the back ribs come 4 toward the wall
// from where that print had them (brd_l = 36), then eased back 0.3 so the
// board drops in. Thickness is NOT measured.
brd_l      = 36.3;  // along X: sets the back ribs (see above)
brd_w      = 19;    // across Y
brd_t      = 1.6;   // (VERIFY — nominal)
usb_over   = 2.0;   // socket overhang past the board edge (measured by hand)
// The end wall is NOTCHED on the inside: a slim slot the width of the board
// and only `notch_h` tall, so the board's edge goes into the wall and is held
// there, top and bottom. The socket shell sits on the board's face-plate side
// and leaves through the opening, which the slot runs into. The board goes in
// AFTER the cradle is screwed down, from the face side: through the open rim
// beyond the cross beam, slid toward the wall nose first, tail then pressed
// onto the cradle between the back ribs. Its depth is whatever puts the socket
// mouth flush with the outside: the wall less the socket's overhang. What is
// left of the wall beyond the pocket is a skin exactly as thick as the
// overhang, and only the shell passes through it. So `usb_over` matters: too
// small a figure leaves the socket proud of the wall, too large leaves it shy.
usb_notch  = wall - usb_over;   // pocket depth into the end wall
notch_cl   = 0.3;   // slot clearance at each side of the board
notch_h    = 2.0;   // slot height: the 1.6 board plus 0.2 above and below
                    // (VERIFY — board thickness is not measured)
brd_x0     = -inner.x/2 - usb_notch;   // board edge at the USB end, on the
                                       // pocket floor; shell mouth at the outside face
// The board lies flat on the FACE side of the cradle, components toward the
// face plate, socket centred on the opening. Deployed (face up) the board is
// right way up and RESTS ON the cradle. The cradle is therefore between the
// board and the lid: with the lid off you see the cradle's back, and the
// board is reached from the face side.
seat_z     = usb_z + usb_shell_h/2 + brd_t;   // cradle surface the board lies on
                                              // (board spans seat_z - brd_t .. seat_z)

// ---- Face (floor exterior, z=0): icon + LED + wordmark ----------------------
// Icon source: logo-icon-filled.svg (logo-icon.svg with all outline holes
// filled so every shape is a solid inset; filtered from NeuromechanicsLabLogo_noface.ai —
// background + text stripped, 26 paths). MEASURED imported bbox (pt units
// import at 0.3528mm/pt): x 15.80..142.23, y 28.62..83.69.
icon_w      = 95;                 // printed icon width
icon_cx     = -22;                // icon center on the face
art_recess  = 1.2;                // recess depth into the face
art_h       = 0.6;                // colored floor slab thickness (3 layers)
art_bleed   = 0.4;                // slab overlaps past the recess edge so no
                                  // body-colored seam shows on the floor
bb_cx       = 79.02;              // measured import-space center
bb_cy       = 56.16;
icon_s      = icon_w / 126.43;    // measured import-space width
// soma (orange dot) center — MEASURED by importing the isolated soma path
// through the same pipeline (import-space center 40.43, 55.56 → offset from
// icon center dx -38.59, dy -0.60). The plate prints face-up so the art is
// NOT mirrored: the offset applies with its own sign.
soma_x      = icon_cx - 38.59 * icon_s;
soma_y      = -0.60 * icon_s;
art_fat     = 0.25;               // stroke fattening: thinnest dendrites become
                                  // ~2mm = 4-5 extrusion lines
wordmark    = "PRE-Sync";
word_font   = "Futura:style=Bold";   // geometric, heavy — matches the logo's circles
word_x      = 50;                 // centered in the clear zone right of icon
word_size   = 7;

// ---- Ground/tether screw (right end wall, dead center) ----------------------
// IDEAL 774044R-style 10-32 thread-forming grounding screw (green): tether
// ring terminal under the head OUTSIDE, screw self-taps the wall — line the
// interior with copper foil over this area and the threads contact it on the
// way through = the shield's single ground point. No nut needed.
gnd_d      = 4.3;   // 10-32 thread-forming bite in 3mm PLA (major dia 4.8)
gnd_y      = 0;
gnd_zp     = 18.5;  // mid-height of the assembled box (lid on)

// ---- Top bracing: ledge, beams, and the cradle pillars -----------------------
// ORIENTATION: the face plate is the TOP of the deployed box and the lid is the
// BOTTOM. In model coordinates the face end is the low-z end, so the ledge and
// beams are built there. Their outer faces are FLUSH with the rim: the frame
// prints rim down, so rim, ledge and beams are all first layer, flat on
// the plate, and the pillars grow vertically off solid material. Recessed even
// slightly they would be 45mm unsupported bridges. Flush also means the face
// plate seats on them, so they must be exactly coplanar with the rim.
ledge_w     = 2.5;   // how far the top lip reaches inward
ledge_h     = 3;     // its thickness in Z
beam_w      = 8;     // beam width along X
beam_h      = 4;     // beam thickness in Z

// Four PILLARS carry the cradle, two each side of the board. Each is a
// square block built against the long wall, from the rim plane to the
// cradle's seat plane (beside the board), so it is part of the wall rather
// than a free post.
// Row 0 also has a full cross beam through it, for bracing. Row 1 has none:
// the face LED comes through the plate at x = -51, between those two.
//
// The cradle is SCREWED on. Each pillar has an M3 clearance hole down its
// axis from the cradle end and a side slot just under that end, the same
// captive-nut scheme as the corner posts. These slots open toward the middle
// of the box (across Y), where there is room to reach. The hole is blind: it
// stops 2.6mm short of the rim face, so neither nut nor screw comes anywhere
// near the face plate.
pil_x       = [-64, -50];   // row 0 leaves 8mm to the corner posts, for
                            // sliding nuts into those posts' slots
pil_y       = 17;    // +/- : screw axis, well clear of the board and its ribs
pil_w       = 10;    // block side along X; across Y it runs out to the wall
pil_nut_in  = 1.6;   // plastic between the pillar end and its nut slot
// Screw: strap 2.4 + 1.6 + nut 2.4 = 6.4  ->  M3 x 8 pan head.
// Two plain beams brace the rest of the long walls (they carry nothing).
brace_x     = [5, 55];

// ---- Cradle (separate part, ASA) ---------------------------------------------
// A flat base the board lies on, L ribs at the inner corners, side ribs near
// the wall, and the wall end open for the socket. Two straps reach out to
// four M3 clearance holes over the pillars; the straps sit flat on the pillar
// ends. Silicone the board in.
crd_base_t  = 2.4;
crd_rib_t   = 1.2;
crd_rib_h   = 3.0;
crd_clear   = 0.3;   // board to rib
crd_leg     = 6;     // rib leg length
crd_strap_w = pil_w + 1;             // strap width along X
crd_x0      = -inner.x/2;            // wall end of the base: FLUSH against the
                                     // end wall. A base that stops short of the
                                     // wall lets the board slide forward off its
                                     // back ribs. The board overhangs the base
                                     // into the notch.
crd_x1      = brd_x0 + brd_l + crd_clear + crd_rib_t;   // inner end of the base
crd_hw      = brd_w/2 + crd_clear + crd_rib_t;          // base half-width
crd_strap_hw = pil_y + 4.5;                              // strap half-length
pil_end_z   = seat_z;   // pillar ends bear on the straps, in the seat plane

// ---- Corner posts with captive M3 nuts ---------------------------------------
// Square blocks merged into the corners, on the same centres as the eight-
// output box's round posts, so the face plate's four holes still line up.
// Each end of each block has a clearance hole down its axis and a sideways
// slot a few mm in. The slot runs at 45 degrees, out through the post's inner
// corner toward the middle of the box; a hex nut slides in until it is under
// the hole. Printed rim-down, each slot's
// roof is a ~6mm bridge.
post_w      = 10;    // block side
nut_af      = 5.5;   // M3 hex nut across flats (VERIFY on fit_test — nominal)
nut_t       = 2.4;   // nut thickness (VERIFY — nominal)
nut_cl      = 0.3;   // slot clearance, on flats and on thickness
nut_in      = 3.5;   // plastic between the post end and the slot
screw_cl_d  = 3.4;   // M3 clearance
screw_past  = 4;     // hole continues this far past the nut for the screw tip
// Screw: plate 3 + nut_in 3.5 + nut 2.4 = 8.9  ->  M3 x 10 countersunk, both ends.

// ---- Lid keyhole mounts -----------------------------------------------------
key_x      = 45;    // two pads at ±key_x, centered in y
key_pad_d  = 16;
key_pad_h  = 3;     // added thickness (lid wall 3 -> 6 at the pads)
key_head_d = 8.6;   // clears an M4 / #8 screw head
key_slot_w = 4.5;   // shank slot
key_slide  = 9;     // slot length; slots point toward the box front
// Counterbore on the OUTSIDE face, so a mounted screw head sits BELOW the
// lid's outer surface. Without it the head stands proud of an otherwise flat
// bottom and the box rocks on two screw heads whenever it is set on a bench —
// the mount is only used on a wall, but the box spends most of its life on a
// table. Depth is most of the wall; the remaining material still carries the
// slot, which is what takes the load once the screw slides home.
key_cbore_d = 15;   // clears the head plus the driver's reach
key_cbore_h = 2.0;  // of wall = 3, leaving 1 mm under the slot

// ---- Labels (all INSET) -----------------------------------------------------
label_size   = 4.6;
label_font   = "Futura:style=Medium";  // walls: medium weight, slightly larger,
                                       // so counters stay open in the grooves
label_deboss = 0.8;    // depth into the wall
label_fat    = 0.2;    // light fattening only (Bold + 0.35 blended letters)

// 2D content debossed INTO the front (+Y) face. The box deploys FACE-UP
// (flipped 180° from model orientation), so glyphs are rotated 180° in-plane
// to read upright on the deployed box.
module front_deboss_2d(x, z) {
  translate([x, inner.y/2 + wall + 0.01, z])
    rotate([90, 0, 0])
      linear_extrude(label_deboss + 0.02)
        mirror([1, 0, 0]) children();
}
module fat_text(s) {
  offset(r = label_fat)
    text(s, size = label_size, font = label_font,
         halign = "center", valign = "center");
}
module front_text(s, x, z) { front_deboss_2d(x, z) rotate(180) fat_text(s); }
module left_text(s, y, z) {
  translate([-(inner.x/2 - inner.y/2), 0, 0])
    rotate([0, 0, 90]) front_text(s, y, z);
}
// face art 2D — the plate prints face-UP, so the art reads as-is from +z.
module face_art_2d() {
  difference() {
    union() {
      translate([icon_cx, 0])
        offset(r = art_fat)
          scale([icon_s, icon_s])
            translate([-bb_cx, -bb_cy])
              import("logo-icon-filled.svg");
      translate([word_x, 0])
        offset(r = art_fat)
          text(wordmark, size = word_size, font = word_font,
               halign = "center", valign = "center");
      // inset seat for the LED's panel-mount ring, centered on the soma
      translate([soma_x, soma_y]) circle(d = led_ring_d);
    }
    // optional bezel landing: no recess (and no color slab) under a holder
    if (led_bezel_d > 0) translate([soma_x, soma_y]) circle(d = led_bezel_d);
  }
}

// ---- Nut posts ---------------------------------------------------------------
module hex2d(af) { circle(d = af / cos(30), $fn = 6); }   // flats parallel to X

module nut_posts() {
  translate([0, 0, wall]) linear_extrude(inner.z) intersection() {
    for (p = post_xy(inner)) translate(p) square(post_w, center = true);
    rrect(inner.x + 2*wall, inner.y + 2*wall, rad);
  }
}
// Everything removed from one post at one end. `up` = +1 at the face end
// (cuts run toward +z from z0), -1 at the lid end.
module nut_cut(p, z0, up) {
  sx = p.x > 0 ? 1 : -1;
  sy = p.y > 0 ? 1 : -1;
  a  = atan2(-sy, -sx);        // 45 degrees, pointing from the corner into the box
  sh = nut_t + nut_cl;
  translate([p.x, p.y, up > 0 ? z0 - 0.5 : z0 - (nut_in + sh + screw_past)])
    cylinder(d = screw_cl_d, h = nut_in + sh + screw_past + 0.5);
  translate([0, 0, up > 0 ? z0 + nut_in : z0 - nut_in - sh])
    linear_extrude(sh) hull() {
      translate(p) rotate(a) hex2d(nut_af + nut_cl);
      translate([p.x - sx*post_w, p.y - sy*post_w]) rotate(a) hex2d(nut_af + nut_cl);
    }
}

// ---- Frame: walls + corner posts, open at BOTH ends -------------------------
// Modeled in the original floor-at-z=0 coordinates so every wall feature
// keeps its z, then dropped by `wall`: the frame spans z = 0 .. inner.z. The
// face plate screws onto the z=0 end, the lid onto the z=inner.z end.
module frame_model() {
  translate([0, 0, -wall]) difference() {
    union() {
      translate([0, 0, wall]) linear_extrude(inner.z) difference() {
        rrect(inner.x + 2*wall, inner.y + 2*wall, rad);
        rrect(inner.x, inner.y, max(rad - wall, 0.5));
      }
      nut_posts();

      // stiffening ledge around the top opening (turns the free edge of the
      // 168mm walls into a flange)
      translate([0, 0, wall])
        linear_extrude(ledge_h) difference() {
          rrect(inner.x, inner.y, max(rad - wall, 0.5));
          rrect(inner.x - 2*ledge_w, inner.y - 2*ledge_w, max(rad - wall - ledge_w, 0.5));
        }

      // full cross beams: pillar row 0, and the two plain braces
      for (x = concat([pil_x[0]], brace_x))
        translate([x - beam_w/2, -inner.y/2, wall])
          cube([beam_w, inner.y, beam_h]);
      // the four pillars: blocks against the long walls
      for (x = pil_x, sy = [-1, 1])
        translate([x - pil_w/2, sy > 0 ? pil_y - pil_w/2 : -inner.y/2, wall])
          cube([pil_w, inner.y/2 - pil_y + pil_w/2, pil_end_z - wall]);
    }
    // ---- cradle screws: blind hole + side nut slot in each pillar -----------
    for (x = pil_x, sy = [-1, 1]) {
      sh = nut_t + nut_cl;
      translate([x, sy*pil_y, pil_end_z - (pil_nut_in + sh + 3)])
        cylinder(d = screw_cl_d, h = pil_nut_in + sh + 3 + 0.5);
      // slot opens toward y = 0; hexagon turned so its flats run along Y
      translate([0, 0, pil_end_z - pil_nut_in - sh]) linear_extrude(sh) hull() {
        translate([x, sy*pil_y]) rotate(90) hex2d(nut_af + nut_cl);
        translate([x, sy*(pil_y - pil_w)]) rotate(90) hex2d(nut_af + nut_cl);
      }
    }
    // ---- captive nuts, both ends of every post -----------------------------
    for (p = post_xy(inner)) {
      nut_cut(p, wall, 1);
      nut_cut(p, wall + inner.z, -1);
    }
    // ---- front: 6 BNC outputs, numbered under each (deployed z≈6) ----------
    for (i = [0 : n_out - 1]) {
      translate([out_x(i), inner.y/2 + wall, front_z])
        rotate([-90, 0, 0]) translate([0, 0, -wall - 0.01])
          round_cutout(wall + 0.02, bnc_d);
      front_text(str(i + 1), out_x(i), 30.5);
    }
    front_text("OUTPUTS", out_cx, 6.5);     // caption rides HIGH when deployed
    // ---- left end: USB-C opening (socket shell only), wall center -----------
    // rotate([0,-90,0]) sends the cutout's local x to model z, so the first
    // size is the opening's HEIGHT and the second its width across Y.
    translate([-inner.x/2 - wall, 0, usb_z])
      rotate([0, -90, 0]) translate([0, 0, -wall - 0.01])
        rect_cutout(wall + 0.02, usb_shell_h, usb_shell_w, 1.5);
    // slot for the board's edge, inside face of the same wall: board width,
    // notch_h tall, centred on the board's thickness
    translate([-inner.x/2 - usb_notch, -brd_w/2 - notch_cl, seat_z - brd_t/2 - notch_h/2])
      cube([usb_notch + 0.01, brd_w + 2*notch_cl, notch_h]);
    left_text("USB", 0, 30.5);
    // ---- right end: 10-32 ground/tether screw hole, wall center -------------
    translate([inner.x/2 + wall, gnd_y, gnd_zp])
      rotate([0, 90, 0]) translate([0, 0, -wall - 0.01])
        round_cutout(wall + 0.02, gnd_d);
  }
}

// ---- Cradle ------------------------------------------------------------------
// Drawn at the board's x/y in the frame, seat face UP (z = crd_base_t), flat
// underside on the bed, which is how it prints. In the frame it is turned
// over about the X axis so the seat faces the face plate; it is symmetric in
// Y, so turning it over changes nothing in plan. The straps bear on the
// pillar ends with the same face the board lies on.
module cradle_2d() {
  translate([crd_x0, -crd_hw]) square([crd_x1 - crd_x0, 2*crd_hw]);
  for (x = pil_x)
    translate([x - crd_strap_w/2, -crd_strap_hw]) square([crd_strap_w, 2*crd_strap_hw]);
}
module cradle_model() {
  xe = brd_x0 + brd_l + crd_clear;   // inner face of the end rib
  ye = brd_w/2 + crd_clear;          // inner face of a side rib
  difference() {
    union() {
      linear_extrude(crd_base_t) offset(r = 1) offset(delta = -1) cradle_2d();
      translate([0, 0, crd_base_t]) linear_extrude(crd_rib_h) {
        for (sy = [-1, 1]) {
          // end rib legs (inner corners)
          translate([xe, sy > 0 ? ye + crd_rib_t - crd_leg : -ye - crd_rib_t])
            square([crd_rib_t, crd_leg]);
          // side rib legs: one at the inner corner, one near the wall
          for (x0 = [xe + crd_rib_t - crd_leg, crd_x0])
            translate([x0, sy > 0 ? ye : -ye - crd_rib_t])
              square([crd_leg, crd_rib_t]);
        }
      }
    }
    for (x = pil_x, sy = [-1, 1])
      translate([x, sy*pil_y, -0.5])
        cylinder(d = screw_cl_d, h = crd_base_t + 1);
  }
}
// the cradle where it sits in the frame's final coordinates (preview only)
module cradle_placed() {
  translate([0, 0, seat_z - wall + crd_base_t]) rotate([180, 0, 0]) cradle_model();
}
module board_placed() {
  translate([brd_x0, -brd_w/2, seat_z - wall - brd_t]) cube([brd_l, brd_w, brd_t]);
}

// ---- Face plate: flat, prints face-up (z=0 interior, z=wall = the face) ----
face_screw_d = 3.4;   // M3 clearance; countersunk head on the face
module face_plate() {
  difference() {
    linear_extrude(wall) rrect(inner.x + 2*wall, inner.y + 2*wall, rad);
    for (p = post_xy(inner)) {
      translate([p.x, p.y, -0.5]) cylinder(d = face_screw_d, h = wall + 1);
      translate([p.x, p.y, wall * 0.3])
        cylinder(d1 = face_screw_d, d2 = face_screw_d * 2, h = wall * 0.7 + 0.01);
    }
    // art recess from the face
    translate([0, 0, wall - art_recess]) linear_extrude(art_recess + 0.01) face_art_2d();
    // carve out the colored floor slab's volume (it comes back as face_art)
    translate([0, 0, wall - art_recess - art_h - 0.01]) linear_extrude(art_h + 0.02)
      offset(r = art_bleed) face_art_2d();
    // panel-mount LED holder through the soma
    translate([soma_x, soma_y, -0.5]) cylinder(d = led_d + 2*fit, h = wall + 1);
  }
}

// The colored floor slab: art footprint (+bleed), art_h thick, directly under
// the recess inside the plate. LED hole re-cut so it never covers the LED.
module face_art_model() {
  difference() {
    translate([0, 0, wall - art_recess - art_h]) linear_extrude(art_h)
      offset(r = art_bleed) face_art_2d();
    translate([soma_x, soma_y, -0.5]) cylinder(d = led_d + 2*fit, h = wall + 1);
  }
}

// ---- Lid (bottom when deployed) with keyhole mounts -------------------------
// The keyhole pads go on the INSIDE face, not the outside.
//
// Outside, they are two 3 mm bosses standing proud of an otherwise flat
// bottom, so a box set down on a bench rocks on them. Inside, the outer face
// stays flat and the pad still does its job: it is there to give the screw
// head somewhere to sit and to thicken the wall around the keyhole, and it
// does that from either side. The lip already sets the interior clearance, so
// the pads sit within it and do not foul the frame.
// Flat lid with an inner lip, as the library's lid(), but the lip's corner
// notches are square to clear the nut posts.
module lid_nut(lip_h = 3) {
  difference() {
    union() {
      linear_extrude(wall) rrect(inner.x + 2*wall, inner.y + 2*wall, rad);
      translate([0, 0, wall]) linear_extrude(lip_h) difference() {
        rrect(inner.x - 2*fit, inner.y - 2*fit, max(rad - wall, 0.5));
        for (p = post_xy(inner)) translate(p) square(post_w + 2*fit, center = true);
      }
    }
    for (p = post_xy(inner)) {
      translate([p.x, p.y, -0.5]) cylinder(d = screw_cl_d, h = wall + lip_h + 1);
      translate([p.x, p.y, -0.01]) cylinder(d1 = screw_cl_d * 2, d2 = screw_cl_d, h = wall * 0.7);
    }
  }
}

module lid_part() {
  difference() {
    union() {
      lid_nut();
      for (s = [-1, 1])
        translate([s*key_x, 0, wall])
          cylinder(d = key_pad_d, h = key_pad_h);
    }
    // keyholes: head hole + shank slot pointing toward the box FRONT.
    // The counterbore is cut from the outside face (z=0) and swept along the
    // slot, so the head stays recessed through the full travel rather than
    // only where it drops in.
    for (s = [-1, 1]) {
      translate([s*key_x, 0, -0.5])
        cylinder(d = key_head_d, h = wall + key_pad_h + 1);
      translate([s*key_x, 0, 0])
        hull() for (yy = [0, -key_slide])
          translate([0, yy, -0.5])
            cylinder(d = key_slot_w, h = wall + key_pad_h + 1);
      translate([s*key_x, 0, -0.01])
        hull() for (yy = [0, -key_slide])
          translate([0, yy, 0])
            cylinder(d = key_cbore_d, h = key_cbore_h + 0.01);
    }
  }
}

// ---- Fit test: print this before the frame ----------------------------------
// The USB end of the real frame, cut off 3mm past the cradle and 4mm above the
// top of the wall slot. It is the frame's own geometry in the frame's own print
// attitude (rim down), so what fits here fits there: the four pillars at
// their true spacing and length, the end wall with the USB opening at its
// true height, and two corner posts with their face-end nut slots.
// Try: a nut in every slot, the cradle screwed to all four pillars, and the
// board in nose first with the cable plugged in.
// The BNC and LED holes are not on it: their diameters are unchanged
// from the eight-output box, where they were fit-tested.
// Cut height: 4mm of wall above the top of the slot, so the USB opening, the
// slot and the pillars are whole and have a real roof over them. (Cutting relative to
// the pillar ends sliced through the middle of the opening once the pillars
// were shortened.)
fit_top = seat_z - wall + (notch_h - brd_t)/2 + 4;   // 4mm over the slot
module fit_test() {
  intersection() {
    frame_model();
    translate([-inner.x/2 - wall - 1, -inner.y, -1])
      cube([wall + 1 + (crd_x1 + inner.x/2) + 3, 2*inner.y, fit_top + 1]);
  }
}

// assembled preview: frame, cradle and board, face plate flipped onto z=0
module preview() {
  color("gold", 0.5) frame_model();
  color("dimgray") cradle_placed();
  color("#1f2a44") board_placed();
  rotate([180, 0, 0]) { color("gold") face_plate(); color("orangered") face_art_model(); }
}

if (part == "frame") frame_model();
else if (part == "cradle") cradle_model();
else if (part == "face") face_plate();
else if (part == "face_art") face_art_model();
else if (part == "lid") lid_part();
else if (part == "fit_test") fit_test();
else if (part == "preview") preview();
else if (part == "check") { frame_model(); cradle_placed(); board_placed(); }

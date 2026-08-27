// ============================================================================
// trigger-box.scad — PRE-Sync: enclosure for sync_pulse_generator (32U4)
//
// THREE-PART BUILD (no supports anywhere):
//   frame    — the walls + corner posts, open at both ends. 8 BNC outputs on
//              the front (one Arduino pin each, no pots), TRIG IN + FREE/TRIG
//              switch on the back, PWR barrel left end, ground screw centered
//              on the right end, PCB posts inside the rear wall.
//   face     — flat display plate that screws onto one end (countersunk M3
//              self-tappers into the corner posts): Neuromechanics Lab icon
//              + "PRE-Sync" wordmark as a 1.2mm inset whose FLOOR is colored
//              (face_art = the 0.6mm filament-1 slab under the recess), and
//              the panel-mount LED through the neuron's soma.
//   lid      — screws onto the other end; keyhole mounts + attribution.
//
// ALL lettering is inset (debossed) with fattened bold strokes so it prints
// smooth. Deployed: face up, lid down, hung by the lid keyholes.
//
// PRINT — every part flat, as exported, no rotation, no supports:
//   frame     either end down (walls only)
//   face      face UP (as modeled) — import face + face_art into ONE Bambu
//             Studio object: face_art -> filament 1 (orange), face -> 2.
//             Color change = 3 layers just below the top surface.
//   lid       flat as-is
//
// Parts:
//   openscad -o frame.stl     -D 'part="frame"'     trigger-box.scad
//   openscad -o face.stl      -D 'part="face"'      trigger-box.scad
//   openscad -o face_art.stl  -D 'part="face_art"'  trigger-box.scad
//   openscad -o lid.stl       -D 'part="lid"'       trigger-box.scad
//   openscad -o hole_test.stl -D 'part="hole_test"' trigger-box.scad
// ============================================================================

include <lib/nyk-lib.scad>

part = "frame"; // "frame" | "face" | "face_art" | "lid" | "hole_test" | "preview"

// ---- Cavity -----------------------------------------------------------------
inner = [168, 45, 31];
wall  = 3;            // 3mm all walls (keyhole pads on the lid go thicker)
rad   = 3;

// ---- Panel hardware (VERIFY on hole_test) -----------------------------------
bnc_d     = 9.7;   // threaded bulkhead BNC, 3/8" barrel
switch_d  = 6.5;   // SPDT toggle (MTS-102 — 6mm bushing, 6.5 hole fit-tested)
barrel_d  = 11.5;  // 5.5x2.1 panel-mount barrel jack bushing
led_d     = 10.4;  // bare 10mm LED pressed in from the inside; its flange
                   // sits against the plate interior (VERIFY on hole_test)
led_ring_d = 14;   // the LED's panel-mount ring (~11.5 measured) + a style margin:
                   // a circular INSET of this diameter around the hole, same
                   // depth as the art, so the ring sits in it near flush on
                   // the soma's orange floor (VERIFY on hole_test)
led_bezel_d = 0;   // 0 = no raised/flat landing (ring is inset instead)

// ---- Front row (+Y): 8 BNC outputs ------------------------------------------
// 19mm pitch. In the printed/deployed (face-up) box, viewed from the front,
// output 1 is LEFT-most = smallest model x (render-verified).
n_out      = 8;
out_pitch  = 19;
front_z    = 17;
function out_x(i) = (i - (n_out - 1)/2) * out_pitch;   // i = 0..n_out-1

// ---- Rear (-Y): TRIG input + mode switch ------------------------------------
// Whole group lives in the left half of the wall; the right half carries the
// PCB posts/board. Toggle body y-clears the barrel jack's inward protrusion.
ctrl_cx    = -44;   // group center (CONTROL header rides here too)
trig_x     = ctrl_cx + 17;   // IN jack (deployed viewed-left of the toggle)
mode_x     = ctrl_cx - 17;   // toggle; TRIG/RUN label on the BNC side
rear_z     = 17;

// ---- Left end (-X): power barrel, centered ----------------------------------
barrel_z   = 17;

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

// ---- PCB posts: rear (CONTROL) wall, right half -----------------------------
// Four posts protrude horizontally from the wall interior; the FULL uncut
// 80 x 20 proto board mounts VERTICALLY on their ends (M2.5 self-tappers).
pcb_cx     = 34;    // post group center — board spans ~-6..74
pcb_dx     = 76;    // corner hole spacing along the wall (VERIFY!)
pcb_dz     = 15;    // corner hole spacing vertically (VERIFY!)
pcb_cz     = 17;    // group center height = connector height
pcb_post_d = 5.5;
pcb_post_len = 6;   // board face floats 6mm off the wall interior
pcb_pilot  = 2.2;   // M2.5 self-tappers into the post ends

// ---- Lid keyhole mounts -----------------------------------------------------
key_x      = 45;    // two pads at ±key_x, centered in y
key_pad_d  = 16;
key_pad_h  = 3;     // added thickness (lid wall 3 -> 6 at the pads)
key_head_d = 8.6;   // clears an M4 / #8 screw head
key_slot_w = 4.5;   // shank slot
key_slide  = 9;     // slot length; slots point toward the box front

// ---- Labels (all INSET) -----------------------------------------------------
label_size   = 4.6;
label_font   = "Futura:style=Medium";  // walls: medium weight, slightly larger,
                                       // so counters stay open in the grooves
label_deboss = 0.8;    // depth into the wall
label_fat    = 0.2;    // light fattening only (Bold + 0.35 blended letters)
label_pitch  = 6;      // line pitch for stacked two-line labels

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
module rear_text(s, x, z)  { rotate([0, 0, 180]) front_text(s, -x, z); }
// stacked two-line variants (line pitch 5) — s1 reads on TOP once the box
// is deployed (flipped), so s1 sits at the LOWER model z
module rear_text2(s1, s2, x, z)  { rear_text(s1, x, z - label_pitch/2);  rear_text(s2, x, z + label_pitch/2); }
module left_text(s, y, z) {
  translate([-(inner.x/2 - inner.y/2), 0, 0])
    rotate([0, 0, 90]) front_text(s, y, z);
}
// "bus rail": rounded line flowing +x with an arrowhead ON the line at head_at
module bus_arrow_2d(len, w = 1.6, head_at = 0, head_l = 4.5, head_w = 4.6) {
  offset(r = 0.5) offset(delta = -0.5) union() {
    hull() {
      translate([-len/2, 0]) circle(d = w);
      translate([ len/2, 0]) circle(d = w);
    }
    translate([head_at, 0])
      polygon([[0, head_w/2], [head_l, 0], [0, -head_w/2]]);
  }
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
      screw_posts(inner, wall, pilot_both = true);
      // PCB posts off the rear wall interior (flared root for strength)
      for (sx = [-1, 1], sz = [-1, 1])
        translate([pcb_cx + sx*pcb_dx/2, -inner.y/2, pcb_cz + sz*pcb_dz/2])
          rotate([-90, 0, 0]) {
            cylinder(d1 = pcb_post_d + 3, d2 = pcb_post_d, h = 2);
            cylinder(d = pcb_post_d, h = pcb_post_len);
          }
    }
    // ---- front: 8 BNC outputs, numbered under each (deployed z≈6) ----------
    for (i = [0 : n_out - 1]) {
      translate([out_x(i), inner.y/2 + wall, front_z])
        rotate([-90, 0, 0]) translate([0, 0, -wall - 0.01])
          round_cutout(wall + 0.02, bnc_d);
      front_text(str(i + 1), out_x(i), 30.5);
    }
    front_text("OUTPUTS", 0, 6.5);          // caption rides HIGH when deployed
    // ---- rear: TRIG input + SPDT mode switch --------------------------------
    translate([trig_x, -inner.y/2 - wall, rear_z])
      rotate([90, 0, 0]) translate([0, 0, -wall - 0.01])
        round_cutout(wall + 0.02, bnc_d);
    translate([mode_x, -inner.y/2 - wall, rear_z])
      rotate([90, 0, 0]) translate([0, 0, -wall - 0.01])
        round_cutout(wall + 0.02, switch_d);
    rear_text("CONTROL", ctrl_cx, 6.5);
    rear_text("IN", trig_x, 29.5);
    rear_text2("TRIG", "RUN", mode_x + 11, rear_z);   // BNC side
    rear_text2("FREE", "RUN", mode_x - 11, rear_z);
    // bus rail: TRIG RUN -> the IN jack
    rotate([0, 0, 180]) front_deboss_2d(-3.5 - ctrl_cx, 16)
      bus_arrow_2d(len = 10, head_at = 1);
    // ---- left end: power barrel ---------------------------------------------
    translate([-inner.x/2 - wall, 0, barrel_z])
      rotate([0, -90, 0]) translate([0, 0, -wall - 0.01])
        round_cutout(wall + 0.02, barrel_d);
    left_text("PWR", 0, 30.5);
    // ---- right end: 10-32 ground/tether screw hole, wall center -------------
    translate([inner.x/2 + wall, gnd_y, gnd_zp])
      rotate([0, 90, 0]) translate([0, 0, -wall - 0.01])
        round_cutout(wall + 0.02, gnd_d);
    // pilots into the PCB post ends
    for (sx = [-1, 1], sz = [-1, 1])
      translate([pcb_cx + sx*pcb_dx/2, -inner.y/2 + pcb_post_len - 5, pcb_cz + sz*pcb_dz/2])
        rotate([-90, 0, 0]) cylinder(d = pcb_pilot, h = 5.51);
  }
}

// ---- Face plate: flat, prints face-up (z=0 interior, z=wall = the face) ----
face_screw_d = 3.4;   // M3 self-tapper clearance; countersunk head on the face
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
module lid_part() {
  difference() {
    union() {
      lid(inner, wall, rad);
      for (s = [-1, 1])
        translate([s*key_x, 0, wall])
          cylinder(d = key_pad_d, h = key_pad_h);
    }
    // attribution, inset inside
    translate([0, 4, wall - 0.6]) linear_extrude(0.61)
      offset(r = label_fat)
        text("NEUROMECHANICS LAB", size = 4, font = label_font,
             halign = "center", valign = "center");
    translate([0, -5, wall - 0.6]) linear_extrude(0.61)
      offset(r = label_fat)
        text("PRE-Sync v1 — 2026", size = 3.2, font = label_font,
             halign = "center", valign = "center");
    // keyholes: head hole + shank slot pointing toward the box FRONT
    for (s = [-1, 1]) {
      translate([s*key_x, 0, -0.5])
        cylinder(d = key_head_d, h = wall + key_pad_h + 1);
      translate([s*key_x, 0, 0])
        hull() for (yy = [0, -key_slide])
          translate([0, yy, -0.5])
            cylinder(d = key_slot_w, h = wall + key_pad_h + 1);
    }
  }
}

// ---- Hole test: every hole + a keyhole + an inset label sample --------------
module hole_test() {
  difference() {
    union() {
      linear_extrude(wall) rrect(90, 26, 3);
      translate([32, 0, wall]) cylinder(d = key_pad_d, h = key_pad_h);
    }
    translate([-34, 0, 0]) round_cutout(wall, bnc_d);
    translate([-22, 0, 0]) round_cutout(wall, switch_d);
    translate([ -8, 0, 0]) round_cutout(wall, barrel_d);
    translate([  8, 0, 0]) round_cutout(wall, led_d);
    translate([  8, 0, wall - art_recess]) cylinder(d = led_ring_d, h = art_recess + 0.01);  // ring seat
    translate([-10, -9, wall - label_deboss]) linear_extrude(label_deboss + 0.01) fat_text("OUT 1");
    translate([32, 0, -0.5]) cylinder(d = key_head_d, h = wall + key_pad_h + 1);
    translate([32, 0, 0])
      hull() for (yy = [0, -key_slide])
        translate([0, yy, -0.5]) cylinder(d = key_slot_w, h = wall + key_pad_h + 1);
  }
}

// assembled preview: frame with the face plate flipped onto its z=0 end
module preview() {
  color("gold") frame_model();
  rotate([180, 0, 0]) { color("gold") face_plate(); color("orangered") face_art_model(); }
}

if (part == "frame") frame_model();
else if (part == "face") face_plate();
else if (part == "face_art") face_art_model();
else if (part == "lid") lid_part();
else if (part == "hole_test") hole_test();
else if (part == "preview") preview();

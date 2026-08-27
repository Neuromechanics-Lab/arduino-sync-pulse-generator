// ============================================================================
// pods.scad — PRE-Sync inline accessories: round Ø60 pucks on a shared body.
//
//   ring       — GAIN puck wall, open both ends: BNC IN and OUT on opposite
//                sides (inset labels), 4 internal posts with screw pilots at
//                both ends, 40 tall (the pot body clears the BNC tails).
//   ring_in    — LED / SOUND puck wall: IN jack only, 28 tall.
//   base       — bottom plate: centered keyhole (slot vertical, so the BNCs
//                run left-right when hung) — common to all three pucks.
//   top_gain   — GAIN puck top: pot hole, "GAIN", arc arrow LOW -> HIGH.
//                Inside: IN center -> pot end, wiper -> OUT center, other
//                end -> shield. High-impedance loads only.
//   top_led    — LED puck top: 1/4"-20 nut trap for a hollow GOOSENECK (mic /
//                lamp gooseneck, wires run inside, holds any position).
//   led_head   — screws on the gooseneck's far end: 10mm LED press-fit
//                with the panel-ring seat, wire passage through.
//   top_sound  — SOUND puck top: pocket for a 5V ACTIVE piezo buzzer, grille,
//                VOL pot, and a LEVEL/EDGE toggle: sound for the whole HIGH,
//                or one short blip on each rising edge (RC one-shot inside).
//
// All parts print flat as exported, no supports. Labels inset (Futura
// Medium, same treatment as the box). Screws: M3 self-tappers, countersunk.
//
//   openscad -o pod-ring.stl -D 'part="ring"' pods.scad   (etc.)
// ============================================================================

include <lib/nyk-lib.scad>

part = "ring";   // ring | ring_in | base | top_gain | top_led | led_head | top_sound | preview

// ---- Puck body --------------------------------------------------------------
puck_d   = 60;
wall     = 3;
body_h    = 40;     // GAIN ring height (pot body clears the BNC tails)
body_h_in = 28;     // LED / SOUND ring height (IN jack only)
bnc_d    = 9.7;
bnc_z    = 13;      // BNC centerline above the ring's base end
pot_d    = 7.2;
led_d    = 10.4;    // 10mm LED press-fit
led_ring_d = 14;    // LED panel-ring seat (inset), matches the box face
art_recess = 1.2;

// posts: 4 at 45° off the BNC axis, sunk into the wall
post_d   = 7;
post_r   = puck_d/2 - wall - post_d/2 + 1.5;
post_angles = [45, 135, 225, 315];
pilot_d  = 2.8;
screw_d  = 3.4;

// keyhole (base plate)
key_head_d = 8.6;
key_slot_w = 4.5;
key_slide  = 9;
key_pad_d  = 16;
key_pad_h  = 3;

// gooseneck: 1/4"-20 male ends (the common mic/lamp gooseneck thread).
// Each end screws into a 1/4"-20 HEAT-SET BRASS INSERT (VERIFY your insert's
// OD; ~7.9-8.0 mm inserts want a 7.6 mm hole)
gn_thread_d  = 6.9;   // wire passage / thread clearance beyond the insert
gn_insert_d  = 7.6;
gn_insert_h  = 10;
boss_d       = 20;

// active buzzer (VERIFY against the part you buy)
buzzer_d    = 23.5;   // 23mm 5V active piezo — loud, sounds while HIGH
buzzer_h    = 10;
grille_hole = 2.2;
switch_d    = 6.5;    // MTS-102 SPDT toggle: LEVEL / EDGE

// ---- Labels -----------------------------------------------------------------
label_size   = 4.6;
label_font   = "Futura:style=Medium";
label_deboss = 0.8;
label_fat    = 0.2;
module fat_text(s, size = label_size) {
  offset(r = label_fat)
    text(s, size = size, font = label_font, halign = "center", valign = "center");
}
// deboss 2D children into the top face of a plate of thickness `wall`
module top_deboss() {
  translate([0, 0, wall - label_deboss]) linear_extrude(label_deboss + 0.01) children();
}
// deboss 2D children into the ring's outer wall at angle `a` (0 = +x),
// centered at height z; extruded radially inward (deeper than the wall
// curvature so the whole glyph cuts)
module wall_deboss(a, z) {
  rotate([0, 0, a]) translate([puck_d/2 + 0.01, 0, z])
    rotate([90, 0, -90]) linear_extrude(label_deboss + 0.9) mirror([1, 0, 0]) children();
}
// countersunk screws on the z=0 face (for plates whose outside is z=0)
module plate_screws_bottom() {
  for (a = post_angles) rotate([0, 0, a]) translate([post_r, 0, 0]) {
    translate([0, 0, -0.5]) cylinder(d = screw_d, h = wall + 1);
    translate([0, 0, -0.01]) cylinder(d1 = screw_d * 2, d2 = screw_d, h = wall * 0.7);
  }
}
// deboss 2D children into the z=0 face, mirrored so they read from outside
module bottom_deboss() {
  translate([0, 0, -0.01]) linear_extrude(label_deboss + 0.01) mirror([1, 0, 0]) children();
}

// ---- Shared pieces ----------------------------------------------------------
module plate_disc() { cylinder(d = puck_d, h = wall); }
module plate_screws() {
  for (a = post_angles) rotate([0, 0, a]) translate([post_r, 0, 0]) {
    translate([0, 0, -0.5]) cylinder(d = screw_d, h = wall + 1);
    translate([0, 0, wall * 0.3]) cylinder(d1 = screw_d, d2 = screw_d * 2, h = wall * 0.7 + 0.01);
  }
}

// ---- Ring -------------------------------------------------------------------
module ring(h = body_h, with_out = true) {
  difference() {
    union() {
      difference() {
        cylinder(d = puck_d, h = h);
        translate([0, 0, -1]) cylinder(d = puck_d - 2*wall, h = h + 2);
      }
      for (a = post_angles) rotate([0, 0, a]) translate([post_r, 0, 0])
        cylinder(d = post_d, h = h);
    }
    // pilots, both ends
    for (a = post_angles) rotate([0, 0, a]) translate([post_r, 0, 0]) {
      translate([0, 0, -1]) cylinder(d = pilot_d, h = 13);
      translate([0, 0, h - 12]) cylinder(d = pilot_d, h = 13);
    }
    // BNC IN (+x) and, for the inline GAIN puck, OUT (-x); labels above
    for (s = with_out ? [0, 180] : [0]) rotate([0, 0, s])
      translate([puck_d/2 - wall - 0.5, 0, bnc_z]) rotate([0, 90, 0])
        round_cutout(wall + 1, bnc_d);
    wall_deboss(0, bnc_z + 10) fat_text("IN");
    if (with_out) wall_deboss(180, bnc_z + 10) fat_text("OUT");
  }
}

// ---- Base plate: keyhole ----------------------------------------------------
module base() {
  difference() {
    union() {
      plate_disc();
      translate([0, 0, wall]) cylinder(d = key_pad_d, h = key_pad_h);   // inside
    }
    plate_screws();
    translate([0, 0, -0.5]) cylinder(d = key_head_d, h = wall + key_pad_h + 1);
    hull() for (yy = [0, key_slide])
      translate([0, yy, -0.5]) cylinder(d = key_slot_w, h = wall + key_pad_h + 1);
  }
}

// ---- GAIN top: pot + arc arrow LOW -> HIGH ----------------------------------
// arc arrow around the pot: starts at the LOW end (lower-left, 225°) and
// sweeps CLOCKWISE over the top to the HIGH end (lower-right, -45°)
module arc_arrow_2d(r = 12.5, w = 1.6, a0 = 220, a1 = -40, head_l = 4, head_w = 4.4) {
  steps = 40;
  pts = [for (i = [0 : steps]) let(a = a0 + (a1 - a0) * i / steps) [r * cos(a), r * sin(a)]];
  for (i = [0 : steps - 1]) hull() {
    translate(pts[i]) circle(d = w);
    translate(pts[i + 1]) circle(d = w);
  }
  // head at the HIGH end, pointing along the sweep (clockwise = tangent -90°)
  translate(pts[steps]) rotate(a1 - 90)
    polygon([[-head_w/2, 0], [head_w/2, 0], [0, head_l]]);
}
module top_gain() {
  difference() {
    plate_disc();
    plate_screws();
    translate([0, 0, -0.5]) cylinder(d = pot_d + 2*fit, h = wall + 1);
    top_deboss() {
      arc_arrow_2d();
      translate([0, 21]) fat_text("GAIN");
      translate([-15, -12.5]) fat_text("LOW", 3.6);
      translate([15, -12.5]) fat_text("HIGH", 3.6);
    }
  }
}

// ---- LED top: gooseneck boss with a heat-set 1/4"-20 insert ----------------
// Prints flat, boss up. Insert goes in from the top with a soldering iron;
// the gooseneck's male end screws into it, wires pass down through the plate.
boss_h = gn_insert_h + 2;
module top_led() {
  difference() {
    union() {
      plate_disc();
      translate([0, 0, wall]) cylinder(d = boss_d, h = boss_h);
    }
    plate_screws();
    translate([0, 0, wall + boss_h - gn_insert_h]) cylinder(d = gn_insert_d, h = gn_insert_h + 0.01);
    translate([0, 0, -0.5]) cylinder(d = gn_thread_d, h = wall + boss_h + 1);   // wire passage
    top_deboss() translate([0, -22]) fat_text("LED", 3.6);
  }
}

// ---- LED head: screws onto the gooseneck's far end -------------------------
// Heat-set insert in the bottom, 10mm LED press-fit in the top with the
// panel-ring seat, wires through the middle.
head_d = 22;
head_h = gn_insert_h + 2 + 6;
module led_head() {
  difference() {
    cylinder(d = head_d, h = head_h);
    translate([0, 0, -0.01]) cylinder(d = gn_insert_d, h = gn_insert_h);
    translate([0, 0, -0.5]) cylinder(d = gn_thread_d, h = head_h + 1);           // wire passage
    translate([0, 0, head_h - 5]) cylinder(d = led_d + 2*fit, h = 6);           // LED press-fit
    translate([0, 0, head_h - art_recess]) cylinder(d = led_ring_d, h = art_recess + 0.01);
  }
}

// ---- SOUND top: active buzzer pocket + grille + VOL pot ---------------------
// Modeled OUTSIDE face at z=0 (labels + countersinks there), buzzer pocket
// walls growing from z=wall on the inside — prints flat exactly as modeled,
// outside face on the bed.
module top_sound() {
  difference() {
    union() {
      plate_disc();
      translate([0, 0, wall]) difference() {
        cylinder(d = buzzer_d + 2*2, h = buzzer_h);
        translate([0, 0, -0.5]) cylinder(d = buzzer_d + 2*fit, h = buzzer_h + 1);
      }
    }
    plate_screws_bottom();
    // grille: rings of holes over the buzzer's face
    for (r = [4, 8], n = [6, 12]) for (i = [0 : n - 1])
      rotate([0, 0, 360 * i / n + (r == 8 ? 15 : 0)]) translate([r, 0, -0.5])
        cylinder(d = grille_hole, h = wall + 1);
    translate([0, 0, -0.5]) cylinder(d = grille_hole, h = wall + 1);
    // VOL pot and LEVEL/EDGE toggle on opposite sides, both OFF the jack
    // axis (the BNC tail runs through the middle of the puck along x)
    translate([0, -19, -0.5]) cylinder(d = pot_d + 2*fit, h = wall + 1);
    translate([0,  19, -0.5]) cylinder(d = switch_d + 2*fit, h = wall + 1);
    bottom_deboss() {
      translate([-10.5, 23.5]) fat_text("LEVEL", 3.2);
      translate([ 10.5, 23.5]) fat_text("EDGE", 3.2);
      translate([0, -25]) fat_text("VOL", 3.6);
    }
  }
}

// ---- Preview: gain puck assembled -------------------------------------------
module preview() {
  color("gold") base();
  color("gold") translate([0, 0, wall]) ring();
  color("gold") translate([0, 0, wall + body_h]) top_gain();
}

if (part == "ring") ring();
else if (part == "ring_in") ring(body_h_in, false);
else if (part == "base") base();
else if (part == "top_gain") top_gain();
else if (part == "top_led") top_led();
else if (part == "led_head") led_head();
else if (part == "top_sound") top_sound();
else if (part == "preview") preview();

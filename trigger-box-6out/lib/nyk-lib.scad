// ============================================================================
// nyk-lib.scad — shared parametric helpers for the rig's enclosures
// Bring into a part file with:  include <lib/nyk-lib.scad>
// (include, not use — so `fit` and friends are visible too)
// ============================================================================

$fn = $preview ? 32 : 96;

// Printer fit clearance added around anything that must slide/press together.
// Tune once per printer with the test ring in rj45-insert.scad, then leave it.
fit = 0.25;

// ---- 2D ---------------------------------------------------------------------
// Rounded rectangle, centered.
module rrect(w, h, r = 3) {
  offset(r = r) square([max(w - 2*r, 0.1), max(h - 2*r, 0.1)], center = true);
}

// ---- Box shell + lid --------------------------------------------------------
// Open-top box. inner = [x, y, z] usable cavity; floor and walls = `wall`.
// Origin: cavity centered on XY, floor top at z = wall.
module box_shell(inner, wall = 2.4, rad = 3) {
  difference() {
    linear_extrude(inner.z + wall)
      rrect(inner.x + 2*wall, inner.y + 2*wall, rad);
    translate([0, 0, wall])
      linear_extrude(inner.z + 1)
        rrect(inner.x, inner.y, max(rad - wall, 0.5));
  }
}

// Corner screw posts for M3 self-tapping screws (pilot ~2.8mm).
// `snug` sinks each post into the corner walls so it reads as part of the
// corner rather than a free-standing pillar (and steals less cavity space).
// `pilot_both` adds a pilot at the floor end too — for frames open at both
// ends where a plate screws onto each end.
module screw_posts(inner, wall = 2.4, post_d = 7, pilot = 2.8, pilot_depth = 12, snug = 1.5, pilot_both = false) {
  for (x = [-1, 1], y = [-1, 1])
    translate([x * (inner.x/2 - post_d/2 + snug), y * (inner.y/2 - post_d/2 + snug), wall])
      difference() {
        cylinder(d = post_d, h = inner.z);
        translate([0, 0, inner.z - pilot_depth])
          cylinder(d = pilot, h = pilot_depth + 1);
        if (pilot_both)
          translate([0, 0, -1]) cylinder(d = pilot, h = pilot_depth + 1);
      }
}

// Positions matching screw_posts, for drilling the lid.
function post_xy(inner, post_d = 7, snug = 1.5) =
  [for (x = [-1, 1], y = [-1, 1])
    [x * (inner.x/2 - post_d/2 + snug), y * (inner.y/2 - post_d/2 + snug)]];

// Flat lid with an inner lip; screw holes + countersinks over the posts.
module lid(inner, wall = 2.4, rad = 3, lip_h = 3, post_d = 7, screw_d = 3.4) {
  difference() {
    union() {
      linear_extrude(wall)
        rrect(inner.x + 2*wall, inner.y + 2*wall, rad);
      // lip, with corner clearance for the screw posts
      translate([0, 0, wall])
        linear_extrude(lip_h)
          difference() {
            rrect(inner.x - 2*fit, inner.y - 2*fit, max(rad - wall, 0.5));
            for (p = post_xy(inner, post_d))
              translate(p) circle(d = post_d + 2*fit);
          }
    }
    for (p = post_xy(inner, post_d)) {
      translate([p.x, p.y, -0.5]) cylinder(d = screw_d, h = wall + lip_h + 1);
      translate([p.x, p.y, -0.01]) cylinder(d1 = screw_d * 2, d2 = screw_d, h = wall * 0.7);
    }
  }
}

// ---- Cutouts (use inside difference() against a wall) -----------------------
// All cutouts are modeled through a wall of thickness `t`, from z=0 (inside
// face) to z=t (outside face), centered on XY. Position with translate/rotate.

module round_cutout(t, d) {
  translate([0, 0, -0.5]) cylinder(d = d + 2*fit, h = t + 1);
}

module rect_cutout(t, w, h, r = 1) {
  translate([0, 0, -0.5]) linear_extrude(t + 1) rrect(w + 2*fit, h + 2*fit, r);
}

// VL53L0X viewing aperture: flares outward so the wall never clips the
// sensor's ~25° cone. window = the sensor's emitter+receiver window pair
// footprint sitting against the inside face.
module tof_aperture(t, window_w = 8, window_h = 5, half_angle = 13, margin = 1.5) {
  grow = t * tan(half_angle);
  hull() {
    translate([0, 0, -0.01]) linear_extrude(0.02)
      square([window_w + 2*margin, window_h + 2*margin], center = true);
    translate([0, 0, t + 0.01]) linear_extrude(0.02)
      square([window_w + 2*margin + 2*grow, window_h + 2*margin + 2*grow], center = true);
  }
}

// Dovetail cross-section (2D, centered): mouth edge on the y=0 line, root
// at y=-depth (wider). Extrude vertically for rails/slots. THE rig-standard
// mount profile — every attachment's male rail and every box's female slot
// comes from this one module so they always mate.
module dovetail_2d(mouth, root, depth) {
  polygon([[-mouth/2, 0], [mouth/2, 0], [root/2, -depth], [-root/2, -depth]]);
}

// D-series (XLR-style) panel cutout — fits the PENGLIN RJ45 D-type jacks.
// Standard D-series: Ø24 main hole + 2x M3 screw holes DIAGONALLY opposed
// (upper-left / lower-right), on a 19mm x 24mm offset grid — screw centers
// sit ~15.3mm from the middle, clear of the main hole. VERIFY against the
// actual PENGLIN jack with the d_test coupon before printing a full part —
// clones vary.
module dseries_cutout(t, main_d = 24, screw_dx = 19, screw_dy = 24, screw_d = 3.2) {
  round_cutout(t, main_d);
  for (s = [-1, 1])
    translate([-s * screw_dx/2, s * screw_dy/2, 0]) round_cutout(t, screw_d);
}

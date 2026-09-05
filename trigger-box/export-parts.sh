#!/usr/bin/env bash
# Export every part as STL + PNG preview into exports/ (gitignored artifacts).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p exports/stl exports/png
for p in frame face face_art lid hole_test; do
  echo "-- $p"
  openscad -o "exports/stl/trigger-$p.stl" -D "part=\"$p\"" trigger-box.scad 2>/dev/null
  openscad -o "exports/png/trigger-$p.png" --imgsize=1400,1000 --autocenter \
    --viewall --colorscheme=Tomorrow -D "part=\"$p\"" trigger-box.scad 2>/dev/null
done
for p in ring ring_in base top_gain top_led led_head led_head_5mm top_sound; do
  echo "-- pod $p"
  openscad -o "exports/stl/pod-$p.stl" -D "part=\"$p\"" pods.scad 2>/dev/null
  openscad -o "exports/png/pod-$p.png" --imgsize=1400,1000 --autocenter \
    --viewall --colorscheme=Tomorrow -D "part=\"$p\"" pods.scad 2>/dev/null
done
echo "Exported to exports/."

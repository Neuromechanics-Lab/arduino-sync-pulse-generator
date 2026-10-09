#!/usr/bin/env bash
# Export every part as STL + PNG preview into exports/ (gitignored artifacts).
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p exports/stl exports/png
for p in fit_test frame cradle face face_art lid; do
  echo "-- $p"
  openscad -o "exports/stl/trigger6-$p.stl" -D "part=\"$p\"" trigger-box-6out.scad 2>/dev/null
  openscad -o "exports/png/trigger6-$p.png" --imgsize=1400,1000 --autocenter \
    --viewall --colorscheme=Tomorrow -D "part=\"$p\"" trigger-box-6out.scad 2>/dev/null
done
openscad -o "exports/png/trigger6-preview.png" --imgsize=1400,1000 --autocenter \
  --viewall --colorscheme=Tomorrow -D 'part="preview"' trigger-box-6out.scad 2>/dev/null
echo "Exported to exports/."

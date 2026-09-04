#!/bin/sh
# Regenerate the wiring diagram from its WireViz source.
#
#     tools/gen_wiring.sh
#
# Outputs PNG, SVG and an HTML sheet next to the .yml. Needs graphviz on
# PATH and the docs venv (python3 -m venv .venv-docs && .venv-docs/bin/pip
# install wireviz).
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
WV="$ROOT/.venv-docs/bin/wireviz"
[ -x "$WV" ] || { echo "wireviz not found at $WV" >&2; exit 1; }
command -v dot >/dev/null || { echo "graphviz 'dot' not on PATH" >&2; exit 1; }
"$WV" "$ROOT/docs/wiring/presync-harness.yml"
echo "wrote docs/wiring/presync-harness.{png,svg,html}"

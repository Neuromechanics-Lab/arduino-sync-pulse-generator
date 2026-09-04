#!/bin/sh
# Regenerate the Python API documentation from docstrings.
#
#     tools/gen_api_docs.sh
#
# Writes docs/api/. Needs the docs venv:
#     python3 -m venv .venv-docs && .venv-docs/bin/pip install pdoc
set -e
ROOT=$(cd "$(dirname "$0")/.." && pwd)
PDOC="$ROOT/.venv-docs/bin/pdoc"
[ -x "$PDOC" ] || { echo "pdoc not found at $PDOC" >&2; exit 1; }
cd "$ROOT/sync_pulse_generator/utils/python"
"$PDOC" -o "$ROOT/docs/api" -d google \
  presync truth align analyze diagnose timecode edge_sync 2>&1 |
  grep -v '^$' || true
echo "wrote docs/api/"

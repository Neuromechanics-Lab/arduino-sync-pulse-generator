#!/usr/bin/env python3
"""
gen_schematic.py - render docs/wiring/presync-schematic.svg from its
netlist source.

The circuit is small enough that a full EDA package would add a binary
project file nobody can diff and a schematic nobody regenerates. This keeps
the electrical description as text, next to the wiring harness, and draws it.

    python3 tools/gen_schematic.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "wiring" / "presync-schematic.yml"
OUT = ROOT / "docs" / "wiring" / "presync-schematic.svg"

W, H = 1320, 760
FONT = "DejaVu Sans, Helvetica, Arial, sans-serif"


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def main():
    try:
        import yaml
    except ImportError:
        print("needs PyYAML: .venv-docs/bin/pip install pyyaml", file=sys.stderr)
        return 1
    d = yaml.safe_load(SRC.read_text())

    S = []
    A = S.append
    A(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
      f'viewBox="0 0 {W} {H}">')
    A(f'<style>'
      f'text{{font-family:{FONT};}}'
      f'.t{{font-size:19px;font-weight:600;}}'
      f'.s{{font-size:12px;fill:#555;}}'
      f'.lbl{{font-size:12px;}}'
      f'.pin{{font-size:11px;fill:#333;}}'
      f'.note{{font-size:10.5px;fill:#555;}}'
      f'.net{{font-size:11px;fill:#0a6;font-weight:600;}}'
      f'line,path,rect,circle{{stroke:#222;fill:none;stroke-width:1.4;}}'
      f'rect.box{{fill:#fff;}}'
      f'</style>')
    A(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#fff" stroke="none"/>')
    A(f'<text class="t" x="24" y="34">{esc(d["title"])}</text>')
    A(f'<text class="s" x="24" y="54">{esc(d["subtitle"])} '
      f'&#183; electrical schematic (generated)</text>')

    # MCU body
    mx, my, mw, mh = 60, 96, 190, 430
    A(f'<rect class="box" x="{mx}" y="{my}" width="{mw}" height="{mh}" rx="4"/>')
    A(f'<text class="lbl" x="{mx+mw/2}" y="{my+24}" text-anchor="middle" '
      f'font-weight="600">U1  ATmega32U4</text>')
    A(f'<text class="pin" x="{mx+mw/2}" y="{my+42}" text-anchor="middle">'
      f'Pro Micro / Leonardo</text>')

    outs = [p for p in d["blocks"][0]["pins"] if p["dir"] == "out"]
    ins = [p for p in d["blocks"][0]["pins"] if p["dir"] == "in"]

    # Eight output channels: pin -> series R -> BNC
    y0, dy = my + 70, 34
    rx, jx = 470, 720
    for i, p in enumerate(outs):
        y = y0 + i * dy
        A(f'<text class="pin" x="{mx+mw-10}" y="{y+4}" text-anchor="end">'
          f'{esc(p["id"])}</text>')
        A(f'<line x1="{mx+mw}" y1="{y}" x2="{rx}" y2="{y}"/>')
        # resistor
        A(f'<rect class="box" x="{rx}" y="{y-9}" width="52" height="18"/>')
        A(f'<line x1="{rx+52}" y1="{y}" x2="{jx}" y2="{y}"/>')
        # BNC
        A(f'<circle cx="{jx+14}" cy="{y}" r="9"/>')
        A(f'<circle cx="{jx+14}" cy="{y}" r="2.5" fill="#222"/>')
        A(f'<text class="pin" x="{jx+32}" y="{y+4}">J{i+1}  OUT {i+1}</text>')
    A(f'<text class="pin" x="{rx+26}" y="{y0-16}" text-anchor="middle">'
      f'R1-R8</text>')

    # Trigger input: BNC -> 1k -> pin
    ty = y0 + 8 * dy + 22
    A(f'<text class="pin" x="{mx+mw-10}" y="{ty+4}" text-anchor="end">'
      f'{esc(ins[0]["id"])}</text>')
    A(f'<line x1="{mx+mw}" y1="{ty}" x2="{rx}" y2="{ty}"/>')
    A(f'<rect class="box" x="{rx}" y="{ty-9}" width="52" height="18"/>')
    A(f'<text class="pin" x="{rx+26}" y="{ty-14}" text-anchor="middle">R9 1k</text>')
    A(f'<line x1="{rx+52}" y1="{ty}" x2="{jx}" y2="{ty}"/>')
    A(f'<circle cx="{jx+14}" cy="{ty}" r="9"/>')
    A(f'<circle cx="{jx+14}" cy="{ty}" r="2.5" fill="#222"/>')
    A(f'<text class="pin" x="{jx+32}" y="{ty+4}">J9  TRIG IN</text>')
    # pullup symbol
    A(f'<line x1="{mx+mw+40}" y1="{ty}" x2="{mx+mw+40}" y2="{ty-38}"/>')
    A(f'<text class="net" x="{mx+mw+46}" y="{ty-42}">VCC (internal pullup)</text>')

    # Mode switch
    sy = ty + 46
    A(f'<text class="pin" x="{mx+mw-10}" y="{sy+4}" text-anchor="end">'
      f'{esc(ins[1]["id"])}</text>')
    A(f'<line x1="{mx+mw}" y1="{sy}" x2="{rx+120}" y2="{sy}"/>')
    A(f'<circle cx="{rx+126}" cy="{sy}" r="3" fill="#222"/>')
    A(f'<line x1="{rx+126}" y1="{sy}" x2="{rx+178}" y2="{sy-22}"/>')
    A(f'<circle cx="{rx+182}" cy="{sy-24}" r="3" fill="#fff"/>')
    A(f'<text class="pin" x="{rx+192}" y="{sy-21}">FREE RUN (open)</text>')
    A(f'<circle cx="{rx+182}" cy="{sy+16}" r="3" fill="#222"/>')
    A(f'<line x1="{rx+182}" y1="{sy+16}" x2="{rx+182}" y2="{sy+38}"/>')
    A(f'<text class="pin" x="{rx+192}" y="{sy+19}">TRIG RUN</text>')
    # ground symbol
    gx, gy = rx + 182, sy + 38
    for k, w in enumerate((16, 10, 5)):
        A(f'<line x1="{gx-w}" y1="{gy+k*4}" x2="{gx+w}" y2="{gy+k*4}"/>')
    A(f'<line x1="{mx+mw+40}" y1="{sy}" x2="{mx+mw+40}" y2="{sy-30}"/>')
    A(f'<text class="net" x="{mx+mw+46}" y="{sy-33}">VCC (internal pullup)</text>')
    A(f'<text class="pin" x="{rx+126}" y="{sy+56}" text-anchor="middle">SW1</text>')

    # Notes column
    ny = my + 20
    A(f'<text class="lbl" x="{24}" y="{my+mh+52}" font-weight="600">Notes</text>')
    ny = my + mh + 74
    for b in d["blocks"][1:]:
        note = " ".join((b.get("note") or "").split())
        A(f'<text class="pin" x="24" y="{ny}" font-weight="600">'
          f'{esc(b["name"])} &#8212; {esc(b["desc"])}</text>')
        ny += 16
        # wrap
        words, line = note.split(), ""
        for w in words:
            if len(line) + len(w) > 132:
                A(f'<text class="note" x="24" y="{ny}">{esc(line)}</text>')
                ny += 14
                line = w
            else:
                line = (line + " " + w).strip()
        if line:
            A(f'<text class="note" x="24" y="{ny}">{esc(line)}</text>')
            ny += 20

    A(f'<text class="note" x="{W-24}" y="{H-14}" text-anchor="end">'
      f'Generated from docs/wiring/presync-schematic.yml &#183; '
      f'do not edit by hand</text>')
    A('</svg>')

    OUT.write_text("\n".join(S))
    print(f"wrote {OUT.relative_to(ROOT)}  "
          f"({len(outs)} outputs, {len(ins)} inputs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

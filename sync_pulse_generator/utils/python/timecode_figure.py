"""
timecode_figure.py — concept figure for the hybrid sync signal.

Three stacked panels, each a zoom of the one above, generated from the
reference implementation (timecode.generate_template) so the waveform is
bit-exact with the firmware:

  A  12 s overview: pseudo-random train with the timecode frame at t=10 s
  B  the whole frame: 3-pulse preamble, 52 payload bits, back to random
  C  preamble + first bits at ms scale, each gap labeled

Writes docs/timecode_figure.{svg,png} (annotated) and
docs/timecode_figure_bare.{svg,png} (no labels — annotate from scratch).
SVG output keeps every line/label editable in Illustrator/Inkscape.

    python3 utils/python/timecode_figure.py
"""

import os
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from timecode import (generate_template, TC_PULSE_MS, TC_PREAMBLE_GAP_MS,
                      TC_GAP_ZERO_MS, TC_GAP_ONE_MS)

SEED, RUN_ID, DURATION_S, TC_INTERVAL_S = 42, 0xA5A5, 12, 10   # run ID chosen so the
                                                            # first bits are mixed 1/0
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "docs")
FRAME_SEGMENTS = 109                     # 55 pulses + 54 gaps
FIELDS = [("run ID (16 bits)", 0, 16), ("elapsed seconds (32 bits)", 16, 48),
          ("checksum (4)", 48, 52)]
COL_FRAME, COL_FIELD = "#f4b942", ("#dbe7f5", "#e8f0d8", "#f5dbe1")


def build_signal():
    times, levels = generate_template(SEED, DURATION_S, tc_interval_s=TC_INTERVAL_S,
                                      run_id=RUN_ID)
    times = [t / 1000.0 for t in times]
    # frame = first rising edge at/after the frame due time
    i0 = next(i for i, (t, l) in enumerate(zip(times, levels))
              if t >= TC_INTERVAL_S and l == 1)
    return times, levels, i0


def step_xy(times, levels, t_end):
    xs, ys = [], []
    for t, l in zip(times, levels):
        xs.append(t); ys.append(l)
    xs.append(t_end); ys.append(levels[-1])
    return xs, ys


def draw_signal(ax, times, levels, x0, x1):
    xs, ys = step_xy(times, levels, DURATION_S)
    ax.step(xs, [5 * y for y in ys], where="post", color="black", lw=1.1)
    ax.set_xlim(x0, x1)
    ax.set_ylim(-0.8, 7.2)
    ax.set_yticks([0, 5])
    ax.set_yticklabels(["0 V", "5 V"])
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def gap_span(times, i0, k):
    """(start, end) of payload bit k's gap."""
    j = i0 + 5 + 2 * k
    return times[j], times[j + 1]


def make(annotated):
    times, levels, i0 = build_signal()
    f_start, f_end = times[i0], times[i0 + FRAME_SEGMENTS]
    fig, (axA, axB, axC) = plt.subplots(3, 1, figsize=(12, 8.5),
                                        gridspec_kw={"height_ratios": [1, 1, 1.15]})

    # ---- A: overview -----------------------------------------------------
    draw_signal(axA, times, levels, 0, DURATION_S)
    axA.add_patch(Rectangle((f_start, -0.8), f_end - f_start, 8, color=COL_FRAME,
                            alpha=0.35, lw=0, zorder=0))
    axA.set_xlabel("time (s)")
    if annotated:
        axA.set_title("A   hybrid signal — pseudo-random square wave with one timecode "
                      "frame every 10 s", loc="left", fontsize=11, fontweight="bold")
        axA.annotate("timecode frame\n(t = 10 s)", xy=((f_start + f_end) / 2, 6.6),
                     xytext=((f_start + f_end) / 2 - 2.2, 6.4), ha="right", va="center",
                     fontsize=9, arrowprops=dict(arrowstyle="->", lw=0.9))
        axA.text(0.3, 6.5, "pseudo-random HIGH/LOW durations, 50–500 ms "
                 "(seed 42, xorshift32)", fontsize=9, va="center")

    # ---- B: the frame ------------------------------------------------------
    pad = 0.12
    draw_signal(axB, times, levels, f_start - pad, f_end + 0.35)
    axB.add_patch(Rectangle((f_start, -0.8), f_end - f_start, 8, color=COL_FRAME,
                            alpha=0.18, lw=0, zorder=0))
    axB.set_xlabel("time (s)")
    if annotated:
        axB.set_title("B   one frame: 3-pulse preamble, then 52 bits encoded as the gap "
                      "between 5 ms pulses", loc="left", fontsize=11, fontweight="bold")
        pre_end = times[i0 + 5]
        axB.annotate("", xy=(f_start, 6.2), xytext=(pre_end, 6.2),
                     arrowprops=dict(arrowstyle="|-|", lw=0.9))
        axB.text((f_start + pre_end) / 2, 6.75, "preamble", ha="center", fontsize=8)
        for n, (name, b0, b1) in enumerate(FIELDS):
            s, _ = gap_span(times, i0, b0)
            _, e = gap_span(times, i0, b1 - 1)
            axB.add_patch(Rectangle((s, -0.6), e - s, 6.2, color=COL_FIELD[n],
                                    alpha=0.9, lw=0, zorder=0))
            axB.text((s + e) / 2, 6.5, name, ha="center", fontsize=8)
        axB.text(f_end + 0.03, 6.5, "random resumes", fontsize=8, ha="left")
        axB.text(f_start - pad + 0.005, 6.5, "random", fontsize=8, ha="left")

    # ---- C: ms scale -------------------------------------------------------
    last_bit = 5
    c0, c1 = f_start - 0.015, gap_span(times, i0, last_bit)[1] + 0.012
    draw_signal(axC, times, levels, c0, c1)
    axC.set_xlabel("time (s)")
    if annotated:
        axC.set_title(f"C   preamble gaps = {TC_PREAMBLE_GAP_MS} ms; payload: "
                      f"{TC_GAP_ZERO_MS} ms gap = 0, {TC_GAP_ONE_MS} ms gap = 1 "
                      f"(pulses always {TC_PULSE_MS} ms)", loc="left", fontsize=11,
                      fontweight="bold")
        # preamble gaps
        for g in (1, 3):
            s, e = times[i0 + g], times[i0 + g + 1]
            axC.text((s + e) / 2, 2.5, f"{TC_PREAMBLE_GAP_MS}", ha="center", va="center",
                     fontsize=8, color="#555")
        # payload bits
        for k in range(last_bit + 1):
            s, e = gap_span(times, i0, k)
            ms = round((e - s) * 1000)
            bit = 1 if ms == TC_GAP_ONE_MS else 0
            axC.text((s + e) / 2, 2.5, str(bit), ha="center", va="center", fontsize=12,
                     fontweight="bold")
            axC.text((s + e) / 2, 1.3, f"{ms} ms", ha="center", va="center", fontsize=7,
                     color="#555")
            axC.text((s + e) / 2, 6.3, f"bit {k}", ha="center", fontsize=7, color="#555")
        axC.text(f_start - 0.013, 6.3, "preamble", fontsize=8)

    fig.tight_layout(h_pad=1.6)
    os.makedirs(OUT_DIR, exist_ok=True)
    stem = "timecode_figure" + ("" if annotated else "_bare")
    for ext in ("svg", "png"):
        fig.savefig(os.path.join(OUT_DIR, f"{stem}.{ext}"), dpi=220)
    plt.close(fig)
    return os.path.join(OUT_DIR, f"{stem}.png")


if __name__ == "__main__":
    for a in (True, False):
        print("wrote", os.path.normpath(make(a)))

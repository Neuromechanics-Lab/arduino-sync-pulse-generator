"""
report - state the findings so a person can act on them.

The point of this stage is that the analysis has to be readable without
anyone standing over it interpreting the numbers. Every figure gets its
consequence spelled out: not "2.49 ms jitter" but "half a tick of scatter,
17% of edges land on the wrong tick".
"""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from .signal import STEP_MS


@dataclass
class Report:
    measurements: list = field(default_factory=list)
    combined: object = None
    source: str = ""
    lsl_offsets: dict = field(default_factory=dict)

    def __str__(self):
        return self.text()

    def text(self):
        L = []
        A = L.append
        A("=" * 78)
        A(f"PRE-Sync analysis{('  ' + self.source) if self.source else ''}")
        A("=" * 78)
        A("")
        A(f"{'stream':<22}{'captured':>10}{'jitter':>9}{'quanta':>8}"
          f"{'on-tick':>9}{'drift':>10}{'outages':>9}")
        A("-" * 78)
        for m in self.measurements:
            if not (m.location and m.location.found):
                A(f"{m.name:<22}{'NOT LOCATED':>55}")
                continue
            A(f"{m.name:<22}{m.capture_pct:>9.1f}%{m.jitter_ms:>8.2f}ms"
              f"{m.quanta:>8.3f}{m.within_half_quantum_pct:>8.1f}%"
              f"{m.drift_ppm:>+9.0f}p{len(m.outages):>9}")
        A("-" * 78)
        A("")
        A(f"quanta = jitter / {STEP_MS:g} ms generator step. Under 0.5 means")
        A("every edge lands on the tick the generator actually emitted.")
        A("drift in ppm: 100 ppm is 0.36 s per hour, and streaming layers")
        A("reconcile offset between machines but do not correct rate.")
        A("")
        for m in self.measurements:
            L.extend(self._stream(m))
        if self.combined is not None:
            L.extend(self._combined())
        return "\n".join(L)

    def _stream(self, m):
        L = [f"--- {m.name} " + "-" * max(0, 74 - len(m.name)), ""]
        loc = m.location
        if not (loc and loc.found):
            L.append("  NOT LOCATED in the emitted sequence.")
            L += [f"    {n}" for n in (loc.notes if loc else [])]
            return L + [""]
        L.append(f"  located by {loc.method} at +{loc.offset_s:.1f} s "
                 f"({loc.offset_s/60:.1f} min) into the run")
        if loc.run_id is not None:
            L.append(f"  run ID {loc.run_id}")
        L.append(f"  duration {m.duration_s:.1f} s, "
                 f"{m.n_captured}/{m.n_expected} emitted edges recorded "
                 f"({m.capture_pct:.1f}%)")
        L.append(f"  offset {m.offset_ms:+.2f} ms  "
                 f"drift {m.drift_ppm:+.0f} ppm  jitter {m.jitter_ms:.2f} ms")
        L.append(f"  {m.within_half_quantum_pct:.1f}% of edges within half a "
                 f"quantum ({STEP_MS/2:g} ms) of the correct tick")
        A = L.append
        if abs(m.offset_ms) > 1:
            A(f"  -> the {m.offset_ms:+.1f} ms offset is constant and fully "
              f"removable.")
        if abs(m.drift_ppm) > 20:
            tot = m.drift_ppm / 1000.0 * m.duration_s
            A(f"  -> drift accumulates to {tot:+.1f} ms across this recording "
              f"and {m.drift_ppm*3.6:+.0f} ms per hour. Correctable, but only "
              f"with a reference like this one.")
        A(f"  -> {m.jitter_ms:.2f} ms of jitter remains after correction. "
          f"This is the floor.")
        if m.n_gross:
            A(f"  -> {m.n_gross} edge(s) beyond 3 quanta, excluded from the "
              f"jitter figure:")
            for t, d in m.gross_times[:8]:
                A(f"       t={t:8.2f}s  {d:+8.2f} ms")
        for a, b, n in m.outages:
            A(f"  -> OUTAGE {a:.2f}-{b:.2f} s ({b-a:.2f} s, {n} edges missing). "
              f"Data loss, not a timing error: no timestamp correction "
              f"recovers it.")
        A(f"  verdict: {m.verdict}")
        for n in m.notes:
            A(f"    note: {n}")
        return L + [""]

    def _combined(self):
        c = self.combined
        L = ["--- across streams " + "-" * 59, ""]
        for n in c.notes:
            L.append(f"  {n}")
        if c.pairs:
            L += ["", "  pairwise disagreement (after locating each "
                      "independently):"]
            for a, b, off, dr in c.pairs:
                L.append(f"    {a} vs {b}: {off:+.2f} ms offset, "
                         f"{dr:+.0f} ppm relative drift")
        for a, b in c.shared_outages:
            L.append(f"  shared outage {a:.2f}-{b:.2f} s: upstream of the "
                     f"recorders")
        if self.lsl_offsets:
            L += ["", "  streaming-layer clock offsets, for comparison:"]
            for k, v in self.lsl_offsets.items():
                L.append(f"    {k}: n={v.size}, median {np.median(v)*1000:+.2f} ms, "
                         f"spread {(v.max()-v.min())*1000:.2f} ms")
            L.append("    the layer reconciles these offsets; it does not "
                     "correct rate, so drift above is unaffected by them.")
        return L + [""]


def to_pdf(rep, path):
    """Write the report with figures."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages

    ok = [m for m in rep.measurements if m.location and m.location.found]
    with PdfPages(path) as pdf:
        # Page 1: the text, so the PDF stands alone.
        fig = plt.figure(figsize=(8.5, 11))
        fig.text(0.05, 0.97, rep.text()[:6000], family="monospace",
                 fontsize=6.2, va="top")
        pdf.savefig(fig); plt.close(fig)

        if not ok:
            return path

        # Residual against time: drift is a slope, jitter is the scatter about
        # it, and an outage is a gap. All three visible at once.
        fig, axes = plt.subplots(len(ok), 1, figsize=(8.5, 2.2*len(ok)+1),
                                 squeeze=False, sharex=True)
        for ax, m in zip(axes[:, 0], ok):
            t = m.matched_times - m.matched_times[0]
            ax.plot(t, m.residual_ms, ".", ms=2, alpha=0.5)
            fitline = m.offset_ms + m.drift_ppm/1000.0 * \
                (m.matched_times - m.matched_times.mean())
            ax.plot(t, fitline, "-", lw=1.2,
                    label=f"{m.drift_ppm:+.0f} ppm")
            for a, b, _ in m.outages:
                ax.axvspan(a - m.matched_times[0], b - m.matched_times[0],
                           color="0.85", zorder=0)
            ax.axhspan(-STEP_MS/2, STEP_MS/2, color="0.92", zorder=0)
            ax.set_ylabel("err (ms)", fontsize=8)
            ax.set_title(f"{m.name}  jitter {m.jitter_ms:.2f} ms  "
                         f"{m.within_half_quantum_pct:.0f}% on tick",
                         fontsize=9)
            ax.legend(fontsize=7); ax.tick_params(labelsize=7)
        axes[-1, 0].set_xlabel("time in recording (s)", fontsize=8)
        fig.suptitle("Timing error vs the emitted signal "
                     "(shaded band = half a quantum)", fontsize=10)
        fig.tight_layout(rect=[0, 0, 1, 0.97])
        pdf.savefig(fig); plt.close(fig)

        # Distribution of the detrended error, one panel per stream.
        fig, axes = plt.subplots(1, len(ok), figsize=(3.2*len(ok), 3.2),
                                 squeeze=False)
        bins = np.arange(-10, 10.5, 0.5)
        for ax, m in zip(axes[0], ok):
            d = m.residual_ms - (m.offset_ms + m.drift_ppm/1000.0 *
                                 (m.matched_times - m.matched_times.mean()))
            inside = d[(d >= bins[0]) & (d <= bins[-1])]
            ax.hist(inside, bins=bins)
            ax.axvline(-STEP_MS/2, color="k", lw=0.8, ls="--")
            ax.axvline(STEP_MS/2, color="k", lw=0.8, ls="--")
            n_out = d.size - inside.size
            ax.set_title(f"{m.name}\n{m.jitter_ms:.2f} ms" +
                         (f"  ({n_out} beyond axis)" if n_out else ""),
                         fontsize=8)
            ax.set_xlabel("error (ms)", fontsize=8); ax.tick_params(labelsize=7)
        fig.suptitle("Error after removing offset and drift "
                     "(dashed = half quantum)", fontsize=10)
        fig.tight_layout(rect=[0, 0, 1, 0.93])
        pdf.savefig(fig); plt.close(fig)
    return path

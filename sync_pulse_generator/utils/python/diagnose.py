#!/usr/bin/env python3
"""
diagnose.py - Answer "can these recordings be aligned, and how well?" without
requiring the analyst to know the generator's configuration, and without
hand-tuning a matching window.

WHY THIS EXISTS SEPARATELY FROM align.py

align.py locks each recording to a template regenerated from the firmware. That
is the stronger method when it applies, but it needs the seed and timing config
to match. It cannot help when:

  * the recording was made with different generator settings, or the simple
    bench firmware, or a box whose configuration was not written down;
  * the signal did not come from a PRE-Sync box at all.

This module aligns two recordings to EACH OTHER using only the pattern of
intervals between their transitions. No template, no seed, no configuration.

WHAT IT GUARDS AGAINST

Every check here exists because the naive version of it produced a confident
wrong answer on real data:

  * Unrelated clock epochs. LSL streams commonly start at arbitrary offsets
    (one recording at t=267947 s, another at t=4454 s). A nearest-neighbour
    matcher run on those will happily pair every edge and report a delay of
    -4616 ms with a 990 ms spread. Alignment therefore starts from an interval
    FINGERPRINT, which is invariant to clock offset, not from the timestamps.

  * Non-overlapping recording windows. One system is almost always stopped
    before the other. Counting transitions that occurred while the other device
    was not recording as "dropped" turned a healthy 2-event shortfall into an
    apparent 85% loss. Loss is only ever counted inside the overlap.

  * Index-walking through inserts. Pairing the nth edge of one stream with the
    nth of the other desynchronises permanently at the first extra or missing
    event. Pairing is by time, after the fit, so a single anomaly costs one
    pair rather than all of them.

  * Clock rate differences. A fixed pairing window assumes both clocks run at
    the same speed; at even 300 ppm the alignment slides out of any sane
    window over a few minutes. Offset and rate are fitted together, iteratively.

Usage:
    from diagnose import diagnose_pair, Recording

    rep = diagnose_pair(
        Recording('kinarm', kinarm_edge_times),
        Recording('ant',    ant_event_times))
    print(rep)                       # plain-text report
    rep.to_pdf('sync_report.pdf')    # plots + diagnosis

CLI:
    python diagnose.py xdf FILE.xdf --report out.pdf
    python diagnose.py xdf FILE_A.xdf FILE_B.xdf --report out.pdf

Dependencies: numpy. matplotlib for PDF output. pyxdf for the XDF loader.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np


# A chunk of this many consecutive intervals is slid along the other recording
# to find the overlap. Long enough to be unique in a pseudo-random train, short
# enough that it is unlikely to span a dropped event.
FINGERPRINT_CHUNK = 12

# Pairing tolerance once offset and rate are fitted. Generous enough for a
# recorder sampling at a few hundred Hz, tight enough to reject a wrong pairing.
PAIR_WINDOW_S = 0.050


@dataclass
class Recording:
    """One recording's transition times, in its own clock.

    times: seconds, any epoch. Only the intervals matter for locating the
           overlap, so two recordings whose clocks disagree by hours still
           align.
    kind:  free-text, for the report ("analog sync", "trigger events", ...).
    """
    name: str
    times: np.ndarray
    kind: str = ""
    stream_start: Optional[float] = None   # for duration accounting
    stream_end: Optional[float] = None
    nominal_rate: Optional[float] = None
    n_samples: Optional[int] = None
    sample_gaps: Optional[np.ndarray] = None   # inter-sample dt, if known

    def __post_init__(self):
        self.times = np.sort(np.asarray(self.times, float).ravel())


@dataclass
class PairReport:
    """The result of comparing two recordings."""
    a: Recording
    b: Recording
    ok: bool
    note: str = ""

    offset_s: float = float("nan")     # b_clock = offset + rate * a_clock
    rate: float = float("nan")
    drift_ppm: float = float("nan")

    overlap_s: float = 0.0
    n_a_in_overlap: int = 0
    n_b_in_overlap: int = 0
    n_matched: int = 0
    n_missing: int = 0                 # in A's overlap, absent from B
    n_extra: int = 0                   # in B's overlap, absent from A
    missing_times: list = field(default_factory=list)
    extra_times: list = field(default_factory=list)

    jitter_sd_ms: float = float("nan")
    jitter_p95_ms: float = float("nan")
    jitter_max_ms: float = float("nan")
    fingerprint_err_ms: float = float("nan")

    pair_a: np.ndarray = field(default_factory=lambda: np.empty(0))
    residual_ms: np.ndarray = field(default_factory=lambda: np.empty(0))

    verdict: str = ""
    findings: list = field(default_factory=list)

    def __str__(self) -> str:
        L = [f"{'='*70}",
             f"SYNC DIAGNOSIS  {self.a.name}  vs  {self.b.name}",
             f"{'='*70}"]
        for r in (self.a, self.b):
            dur = (r.stream_end - r.stream_start) if (
                r.stream_end is not None and r.stream_start is not None) else float("nan")
            span = (r.times[-1] - r.times[0]) if len(r.times) > 1 else 0.0
            L.append(f"  {r.name:22} {len(r.times):6d} transitions   "
                     f"active {span:7.2f}s   stream {dur:7.2f}s   {r.kind}")
        if not self.ok:
            L += ["", f"  COULD NOT ALIGN: {self.note}", "="*70]
            return "\n".join(L)

        L += ["",
              f"  overlap              {self.overlap_s:.2f} s",
              f"  clock rate  B/A      {self.rate:.7f}  ({self.drift_ppm:+.0f} ppm,"
              f" {self.drift_ppm*60/1000:+.2f} ms/min)",
              f"  matched              {self.n_matched} of {self.n_a_in_overlap}"
              f" transitions in the overlap",
              f"  missing from {self.b.name:<9} {self.n_missing}"
              f"  ({100*self.n_missing/max(self.n_a_in_overlap,1):.1f}%)",
              f"  extra in {self.b.name:<13} {self.n_extra}",
              f"  residual jitter      sd {self.jitter_sd_ms:.2f} ms   "
              f"p95 {self.jitter_p95_ms:.2f} ms   max {self.jitter_max_ms:.2f} ms",
              ""]
        L.append(f"  VERDICT: {self.verdict}")
        if self.findings:
            L.append("")
            for f_ in self.findings:
                L.append(f"    - {f_}")
        L.append("="*70)
        return "\n".join(L)

    def to_pdf(self, path: str, title: str = "") -> str:
        """Write a report with plots. Returns the path."""
        return _write_pdf([self], path, title)


# ---------------------------------------------------------------------------
# Core comparison
# ---------------------------------------------------------------------------

def _fingerprint_anchor(ta, tb, chunk=FINGERPRINT_CHUNK):
    """Find where B's interval pattern sits inside A's.

    Works on INTERVALS, so it is immune to the two recordings' clocks having
    unrelated epochs — which is the normal case for LSL streams.
    """
    ia, ib = np.diff(ta), np.diff(tb)
    if len(ia) < chunk or len(ib) < chunk:
        return None
    best = None
    for b0 in range(len(ib) - chunk + 1):
        probe = ib[b0:b0 + chunk]
        for a0 in range(len(ia) - chunk + 1):
            e = np.max(np.abs(ia[a0:a0 + chunk] - probe))
            if best is None or e < best[0]:
                best = (e, a0, b0)
    return best


def _fit(ta, tb, offset, rate, window=PAIR_WINDOW_S, rounds=5):
    """Iterate: pair by predicted time, refit offset and rate, repeat.

    Pairing by time rather than by index is what tolerates an extra or missing
    event without desynchronising everything after it.
    """
    for _ in range(rounds):
        pairs = []
        for t in tb:
            pred = (t - offset) / rate if rate else t - offset
            j = int(np.argmin(np.abs(ta - pred)))
            if abs(ta[j] - pred) <= window:
                pairs.append((ta[j], t))
        if len(pairs) < 4:
            return None, offset, rate
        P = np.array(pairs)
        new_rate, new_off = np.polyfit(P[:, 0], P[:, 1], 1)
        if abs(new_rate - rate) < 1e-12 and abs(new_off - offset) < 1e-9:
            offset, rate = new_off, new_rate
            break
        offset, rate = new_off, new_rate
    return P, offset, rate


def diagnose_pair(a: Recording, b: Recording,
                  window_s: float = PAIR_WINDOW_S) -> PairReport:
    """Compare two recordings of the same sync signal.

    `a` is the reference. Neither recording needs to know the generator's
    configuration, and their clocks may have completely unrelated epochs.
    """
    rep = PairReport(a=a, b=b, ok=False)

    if len(a.times) < FINGERPRINT_CHUNK + 1 or len(b.times) < FINGERPRINT_CHUNK + 1:
        rep.note = (f"need at least {FINGERPRINT_CHUNK+1} transitions in each; "
                    f"have {len(a.times)} and {len(b.times)}")
        return rep

    anc = _fingerprint_anchor(a.times, b.times)
    if anc is None:
        rep.note = "not enough intervals to fingerprint"
        return rep
    err, a0, b0 = anc
    rep.fingerprint_err_ms = err * 1000

    if err > 0.020:
        rep.note = (f"the two recordings do not appear to carry the same signal "
                    f"(best interval-pattern match differs by {err*1000:.0f} ms). "
                    f"Check that both channels are the sync line.")
        return rep

    offset = b.times[b0] - a.times[a0]
    P, offset, rate = _fit(a.times, b.times, offset, 1.0, window_s)
    if P is None:
        rep.note = "found a coarse match but could not converge on a fit"
        return rep

    rep.ok = True
    rep.offset_s = offset
    rep.rate = rate
    rep.drift_ppm = (rate - 1.0) * 1e6

    # --- overlap accounting -------------------------------------------------
    # Only the window both devices were recording can say anything about loss.
    # Outside it, an absent transition means the device was not running, which
    # is not a fault.
    b_in_a = (b.times - offset) / rate
    lo = max(a.times[0], b_in_a[0])
    hi = min(a.times[-1], b_in_a[-1])
    rep.overlap_s = max(0.0, hi - lo)

    a_ov = a.times[(a.times >= lo) & (a.times <= hi)]
    b_ov = b_in_a[(b_in_a >= lo) & (b_in_a <= hi)]
    rep.n_a_in_overlap = len(a_ov)
    rep.n_b_in_overlap = len(b_ov)

    matched_a = set(np.round(P[:, 0], 6))
    matched_b = set(np.round(P[:, 1], 6))
    rep.n_matched = len(P)
    miss = [t for t in a_ov if round(t, 6) not in matched_a]
    extra = [t for t in b.times if (lo <= (t - offset) / rate <= hi)
             and round(t, 6) not in matched_b]
    rep.n_missing = len(miss)
    rep.n_extra = len(extra)
    rep.missing_times = [float(t - a.times[0]) for t in miss]
    rep.extra_times = [float((t - offset) / rate - a.times[0]) for t in extra]

    resid = (P[:, 1] - (rate * P[:, 0] + offset)) * 1000
    rep.pair_a = P[:, 0] - a.times[0]
    rep.residual_ms = resid
    rep.jitter_sd_ms = float(resid.std())
    rep.jitter_p95_ms = float(np.percentile(np.abs(resid), 95))
    rep.jitter_max_ms = float(np.abs(resid).max())

    _judge(rep)
    return rep


def _judge(r: PairReport) -> None:
    """Turn the numbers into a verdict a human can act on."""
    f = r.findings
    loss = 100 * r.n_missing / max(r.n_a_in_overlap, 1)

    # Duration accounting first — it is the most common source of a false
    # "data loss" conclusion.
    for rec, label in ((r.a, "A"), (r.b, "B")):
        if rec.stream_start is not None and rec.stream_end is not None:
            pass
    da = (r.a.stream_end - r.a.stream_start) if r.a.stream_end is not None else None
    db = (r.b.stream_end - r.b.stream_start) if r.b.stream_end is not None else None
    if da is not None and db is not None and abs(da - db) > 1.0:
        longer, shorter = (r.b.name, r.a.name) if db > da else (r.a.name, r.b.name)
        f.append(f"{longer} recorded {abs(db-da):.1f} s longer than {shorter}. "
                 f"Transitions outside the {r.overlap_s:.1f} s overlap are not "
                 f"counted as loss — they occurred while one device was not "
                 f"recording.")

    if loss > 10:
        f.append(f"{r.n_missing} of {r.n_a_in_overlap} transitions inside the "
                 f"overlap ({loss:.0f}%) have no counterpart. This is real loss, "
                 f"not a duration artefact.")
        if r.missing_times:
            burst = _clustered(r.missing_times)
            if burst:
                f.append(f"Losses are clustered, not uniform: "
                         f"{burst}. That pattern suggests intermittent dropout "
                         f"rather than a steady sampling deficit.")
    elif r.n_missing:
        f.append(f"{r.n_missing} transition(s) unmatched inside the overlap "
                 f"({loss:.1f}%) — at this level, as likely edge detection at "
                 f"the recording boundary as true loss.")

    if r.n_extra:
        f.append(f"{r.n_extra} event(s) in {r.b.name} have no counterpart in "
                 f"{r.a.name} inside the overlap. Spurious triggers, or a "
                 f"second signal source on that line.")

    if abs(r.drift_ppm) > 100:
        f.append(f"Clocks differ by {r.drift_ppm:+.0f} ppm "
                 f"({r.drift_ppm*60/1000:+.2f} ms/min). A single constant offset "
                 f"will not hold across a long recording; apply the fitted rate.")

    if r.jitter_sd_ms > 5:
        f.append(f"Residual jitter is {r.jitter_sd_ms:.1f} ms (sd) after fitting "
                 f"offset and rate. Timestamps on one side are not reliable to "
                 f"better than that.")

    # Verdict
    if loss > 10 and r.jitter_sd_ms > 5:
        r.verdict = (f"ALIGNABLE BUT DEGRADED — {loss:.0f}% of transitions lost "
                     f"and {r.jitter_sd_ms:.1f} ms timing jitter.")
    elif loss > 10:
        r.verdict = (f"ALIGNABLE, WITH DATA LOSS — timing is good "
                     f"({r.jitter_sd_ms:.1f} ms) but {loss:.0f}% of transitions "
                     f"are missing.")
    elif r.jitter_sd_ms > 5:
        r.verdict = (f"ALIGNABLE, WITH POOR TIMING — nothing lost, but "
                     f"{r.jitter_sd_ms:.1f} ms jitter limits precision.")
    else:
        r.verdict = (f"CLEANLY ALIGNABLE — {r.jitter_sd_ms:.2f} ms jitter, "
                     f"{loss:.1f}% loss.")


def _clustered(times, gap=2.0):
    """Describe bursts in a list of times, for the findings text."""
    if not times:
        return ""
    t = sorted(times)
    groups, cur = [], [t[0]]
    for x in t[1:]:
        if x - cur[-1] <= gap:
            cur.append(x)
        else:
            groups.append(cur); cur = [x]
    groups.append(cur)
    big = [g for g in groups if len(g) > 1]
    if not big:
        return ""
    return "; ".join(f"{len(g)} in {g[0]:.1f}-{g[-1]:.1f}s" for g in big[:4])


def chunk_by_frames(rep: "PairReport", frames=None, interval_s=None):
    """Split an aligned pair into chunks for per-chunk analysis.

    The intended workflow once every recording carries embedded timecode: the
    decoded frames are natural chunk boundaries, because each is an absolute,
    checksum-verified anchor. Analysis then runs per chunk, and each chunk
    carries its own alignment quality rather than inheriting one number for
    the whole session.

    Two ways to get boundaries:
      frames      a list of anchor times in A's clock (from decode_frames)
      interval_s  fixed-length chunks, for recordings with no timecode — the
                  simple-firmware case, where boundaries are arbitrary but
                  per-chunk quality is still worth knowing

    Returns a list of dicts, one per chunk, each carrying its own matched
    count, loss, jitter and drift. A chunk whose numbers are bad can be
    excluded without discarding the session.
    """
    if not rep.ok:
        return []
    t0 = rep.a.times[0]
    if frames is not None and len(frames) >= 2:
        bounds = [float(f) - t0 for f in sorted(frames)]
    elif interval_s:
        end = rep.a.times[-1] - t0
        bounds = list(np.arange(0, end + interval_s, interval_s))
    else:
        raise ValueError("give either frames= or interval_s=")

    out = []
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        m = (rep.pair_a >= lo) & (rep.pair_a < hi)
        miss = [t for t in rep.missing_times if lo <= t < hi]
        r = rep.residual_ms[m]
        entry = {
            "start_s": float(lo), "end_s": float(hi),
            "n_matched": int(m.sum()), "n_missing": len(miss),
            "jitter_sd_ms": float(r.std()) if len(r) > 1 else float("nan"),
            "jitter_max_ms": float(np.abs(r).max()) if len(r) else float("nan"),
        }
        tot = entry["n_matched"] + entry["n_missing"]
        entry["loss_pct"] = 100.0 * entry["n_missing"] / tot if tot else 0.0
        # A chunk is usable if little was lost and timing held.
        entry["usable"] = (entry["loss_pct"] < 10.0 and
                           (np.isnan(entry["jitter_sd_ms"]) or
                            entry["jitter_sd_ms"] < 5.0))
        out.append(entry)
    return out


def print_chunks(chunks, label="chunk"):
    """Tabulate what chunk_by_frames returned."""
    print(f"\n{'#':>3} {'start':>8} {'end':>8} {'matched':>8} {'lost':>6} "
          f"{'loss%':>7} {'jitter sd':>10} {'usable':>7}")
    for i, c in enumerate(chunks):
        print(f"{i:>3} {c['start_s']:>8.1f} {c['end_s']:>8.1f} "
              f"{c['n_matched']:>8} {c['n_missing']:>6} {c['loss_pct']:>6.1f}% "
              f"{c['jitter_sd_ms']:>9.2f}m {'yes' if c['usable'] else 'NO':>7}")
    bad = [i for i, c in enumerate(chunks) if not c["usable"]]
    if bad:
        print(f"\n  {len(bad)} of {len(chunks)} {label}s unusable: {bad}")
    else:
        print(f"\n  all {len(chunks)} {label}s usable")


# ---------------------------------------------------------------------------
# XDF / LSL loading
# ---------------------------------------------------------------------------

def load_xdf_recordings(path: str, verbose: bool = False):
    """Every stream in an XDF file that carries something edge-like.

    Handles the two shapes seen in practice: an analog channel carrying the
    square wave itself, and a trigger channel carrying brief event pulses.
    Both reduce to transition times.
    """
    import pyxdf
    streams, _ = pyxdf.load_xdf(path, dejitter_timestamps=False,
                                synchronize_clocks=False)
    out = []
    for s in streams:
        info = s["info"]
        name = info["name"][0]
        ts = np.asarray(s["time_stamps"], float)
        d = np.asarray(s["time_series"])
        if d.dtype.kind not in "fiu" or d.ndim != 2 or len(ts) < 3:
            continue

        labels = []
        try:
            labels = [c["label"][0] for c in
                      info["desc"][0]["channels"][0]["channel"]]
        except Exception:
            pass

        best = None
        for c in range(d.shape[1]):
            col = d[:, c].astype(float)
            if not np.isfinite(col).all() or col.std() == 0:
                continue
            lab = labels[c] if c < len(labels) else f"ch{c}"
            lo, hi = col.min(), col.max()
            mid = (lo + hi) / 2
            rises = np.flatnonzero((col[1:] > mid) & (col[:-1] <= mid)) + 1
            if len(rises) < 5:
                continue
            # Prefer an explicitly named trigger, else the most square-like
            # channel (most time spent at the extremes).
            frac_ext = np.mean((col < lo + 0.1*(hi-lo)) | (col > hi - 0.1*(hi-lo)))
            score = frac_ext + (1.0 if "trig" in lab.lower() else 0.0)
            if best is None or score > best[0]:
                best = (score, c, lab, ts[rises])

        if best is None:
            continue
        _, c, lab, rise_t = best
        dt = np.diff(ts)
        kind = "trigger events" if "trig" in lab.lower() else "analog sync"
        out.append(Recording(
            name=f"{name}::{lab}", times=rise_t, kind=kind,
            stream_start=float(ts[0]), stream_end=float(ts[-1]),
            nominal_rate=float(info["nominal_srate"][0] or 0) or None,
            n_samples=len(ts), sample_gaps=dt))
        if verbose:
            print(f"  found {name}::{lab}  {len(rise_t)} rising transitions")
    return out


# ---------------------------------------------------------------------------
# PDF report
# ---------------------------------------------------------------------------

def _write_pdf(reports, path, title=""):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
    except ImportError:
        raise ImportError("matplotlib is required for PDF output "
                          "(pip install matplotlib)")

    with PdfPages(path) as pdf:
        for rep in reports:
            fig = plt.figure(figsize=(8.5, 11))
            def _short(n, w=26):
                # Stream names carry the full LSL identity (device serial plus
                # hostname). Useful in the body, far too long for a heading.
                return n if len(n) <= w else n[:w-3] + "..."
            fig.suptitle(title or f"Sync diagnosis\n{_short(rep.a.name,34)}  vs  "
                                  f"{_short(rep.b.name,34)}",
                         fontsize=11, y=0.985)

            # --- text block ---------------------------------------------------
            ax = fig.add_axes([0.04, 0.58, 0.92, 0.34]); ax.axis("off")
            import textwrap
            body = []
            for line in str(rep).splitlines():
                # Findings are prose and need wrapping; the tabular lines do not.
                body += (textwrap.wrap(line, 118,
                                       subsequent_indent="      ")
                         if len(line) > 118 else [line])
            ax.text(0, 1, "\n".join(body), family="monospace", fontsize=5.6,
                    va="top", ha="left")

            if not rep.ok:
                pdf.savefig(fig); plt.close(fig); continue

            # --- residual over time -------------------------------------------
            ax1 = fig.add_axes([0.10, 0.40, 0.84, 0.16])
            ax1.axhline(0, color="0.7", lw=0.8)
            ax1.plot(rep.pair_a, rep.residual_ms, ".", ms=4,
                     color="#c0392b", label="matched")
            for t in rep.missing_times:
                ax1.axvline(t, color="#2980b9", lw=0.8, alpha=0.6)
            ax1.set_xlabel("time from first transition (s)")
            ax1.set_ylabel("residual (ms)")
            ax1.set_title("Timing residual after fitting offset and rate  "
                          "(blue lines = transitions with no counterpart)",
                          fontsize=8)
            ax1.grid(alpha=0.3)

            # --- residual histogram -------------------------------------------
            ax2 = fig.add_axes([0.10, 0.22, 0.38, 0.13])
            ax2.hist(rep.residual_ms, bins=min(40, max(8, len(rep.residual_ms)//3)),
                     color="#c0392b", alpha=0.8)
            ax2.set_xlabel("residual (ms)"); ax2.set_ylabel("count")
            ax2.set_title("Jitter distribution", fontsize=8)
            ax2.grid(alpha=0.3)

            # --- coverage bar ---------------------------------------------------
            ax3 = fig.add_axes([0.56, 0.22, 0.38, 0.13])
            a_span = (rep.a.times[-1]-rep.a.times[0]) if len(rep.a.times) > 1 else 0
            b_span = (rep.b.times[-1]-rep.b.times[0]) if len(rep.b.times) > 1 else 0
            ax3.barh([1, 0], [a_span, b_span], color=["#2c3e50", "#16a085"],
                     height=0.5)
            ax3.barh([-1], [rep.overlap_s], color="#f39c12", height=0.5)
            ax3.set_yticks([1, 0, -1])
            ax3.set_yticklabels([rep.a.name[:16], rep.b.name[:16], "overlap"],
                                fontsize=7)
            ax3.set_xlabel("seconds")
            ax3.set_title("Recording durations", fontsize=8)
            ax3.grid(alpha=0.3, axis="x")

            # --- interval comparison ---------------------------------------------
            ax4 = fig.add_axes([0.10, 0.05, 0.84, 0.11])
            ax4.plot(rep.a.times[1:] - rep.a.times[0], np.diff(rep.a.times)*1000,
                     ".-", ms=3, lw=0.6, color="#2c3e50", label=rep.a.name[:20])
            b_in_a = (rep.b.times - rep.offset_s) / rep.rate
            ax4.plot(b_in_a[1:] - rep.a.times[0], np.diff(b_in_a)*1000,
                     ".-", ms=3, lw=0.6, color="#16a085", label=rep.b.name[:20])
            ax4.set_xlabel("time (s)"); ax4.set_ylabel("interval (ms)")
            ax4.set_title("Transition intervals — a divergence here is a lost or "
                          "spurious event", fontsize=8)
            ax4.legend(fontsize=6); ax4.grid(alpha=0.3)

            pdf.savefig(fig); plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        description="Diagnose whether two recordings of a sync signal align.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("xdf", help="compare sync streams in XDF file(s)")
    p.add_argument("files", nargs="+")
    p.add_argument("--report", help="write a PDF here")
    p.add_argument("--ref", help="substring naming the reference stream")

    a = ap.parse_args(argv)

    recs = []
    for f in a.files:
        got = load_xdf_recordings(f)
        print(f"{os.path.basename(f)}: {len(got)} sync-bearing stream(s)")
        for r in got:
            print(f"   {r.name}  {len(r.times)} transitions  {r.kind}")
        recs += got

    if len(recs) < 2:
        print("\nNeed at least two sync-bearing streams to compare.")
        return 1

    if a.ref:
        ref = next((r for r in recs if a.ref.lower() in r.name.lower()), recs[0])
    else:
        # Default reference: the device that recorded the WAVEFORM, not the one
        # that recorded events. The waveform recorder sees the signal directly,
        # so it is the ground truth against which the other is judged; picking
        # by transition count instead can select the event stream and make the
        # report read backwards ("missing from <the reliable device>").
        analog = [r for r in recs if r.kind == "analog sync"]
        ref = (max(analog, key=lambda r: len(r.times)) if analog
               else max(recs, key=lambda r: len(r.times)))

    reports = []
    for r in recs:
        if r is ref:
            continue
        rep = diagnose_pair(ref, r)
        print("\n" + str(rep))
        reports.append(rep)

    if a.report and reports:
        _write_pdf(reports, a.report)
        print(f"\nWrote {a.report}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli())

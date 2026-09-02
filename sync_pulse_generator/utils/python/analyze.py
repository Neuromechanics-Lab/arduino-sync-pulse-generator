#!/usr/bin/env python3
"""
analyze.py - One call, full analysis, full report.

    python analyze.py recording.xdf --pdf report.pdf
    python analyze.py a.xdf b.xdf --pdf report.pdf

    from analyze import analyze_file
    rep = analyze_file("recording.xdf")
    rep.to_pdf("report.pdf")

Everything the toolkit can determine about a set of recordings that share the
PRE-Sync signal, in the order it has to be determined, with each quantity kept
separate from the others.

WHAT IT MEASURES AND WHY EACH ONE IS SEPARATE

Lumping these together is how the same recording came to report anywhere from
0.5 ms to 2.6 ms of "jitter" depending on how it was sliced. Each has a
different cause and a different remedy:

  OFFSET      A constant lag. Correctable exactly, by subtraction. If this is
              all that is wrong, the acquisition software's own timestamps can
              be trusted.

  DRIFT       The recorder's clock running fast or slow, in parts per million.
              ACCUMULATES: 65 ppm is 3.9 ms after a minute and 234 ms after an
              hour. Invisible without an external reference — each device
              believes its own clock — so acquisition software cannot remove
              it. This is the strongest reason to record the sync signal.
              Effectively linear over minutes; fit per chunk over hours, since
              a warming crystal curves.

  JITTER      What remains once offset and drift are removed. Irreducible, and
              therefore the precision floor for any analysis. Reported in ms
              and in PRE-Sync quanta.

  GROSS       Individual transitions off by more than a few quanta. Corrupt
              timestamps, not spread — ONE sample 28 ms out took a stream's
              apparent jitter from 0.53 ms to 2.44 ms while the other 142 were
              fine. Counted and located, never averaged into jitter.

  OUTAGES     Runs of consecutive missing transitions: the stream stopped. One
              event however long. A 7.4 s stall and steady low-grade loss are
              different faults, and reporting both as "percent lost" hides
              which one you have.

  ISOLATED    Single misses with intact neighbours — a detection failure
              rather than an interruption.

THE QUANTUM AS THE UNIT

The generator emits only multiples of 5 ms, so that is the natural yardstick.
A recorder whose error stays inside +/- half a quantum can never place a
transition on the wrong tick, whatever its millisecond figure. That is an
acceptance criterion defined by the instrument rather than by taste.

WHAT MAKES THE LOCK SURVIVE REAL DATA

  * The generator is usually ALREADY RUNNING when recording starts. Two real
    recordings from one continuous run sat 17.9 and 41.1 minutes into it;
    searching only the opening reports "no seed matches" on a perfect file.
  * Absolute millisecond tolerances cannot survive drift or loss, so matching
    compares interval RATIOS.
  * Candidates are scored by how many events land on a real transition once
    anchored, not by how many windows agree — a recording with a damaged
    opening scores badly on the latter while being perfectly alignable.

Timecode frames, when the firmware emits them, are used IN ADDITION: they give
absolute position and run identity without a search, and they are the natural
chunk boundaries for per-chunk drift fitting.

Dependencies: numpy; matplotlib for PDF; pyxdf for XDF input.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

import truth
import timecode as tc

STEP_MS = truth.STEP_MS


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass
class Stream:
    """One recorded channel carrying the sync signal."""
    name: str
    times: np.ndarray                 # transition times, the recorder's clock
    both_edges: bool = True           # False for a trigger line logging rises
    kind: str = ""
    nominal_rate: Optional[float] = None
    n_samples: Optional[int] = None
    stream_start: Optional[float] = None
    stream_end: Optional[float] = None
    clock_offset: Optional[float] = None   # what the software claimed
    sample_gaps: Optional[np.ndarray] = None

    def __post_init__(self):
        self.times = np.sort(np.asarray(self.times, float).ravel())

    @property
    def duration_s(self):
        if self.stream_start is None or self.stream_end is None:
            return float("nan")
        return self.stream_end - self.stream_start


@dataclass
class StreamResult:
    stream: Stream
    source: str = ""
    cls: dict = field(default_factory=dict)     # truth.classify output
    frames: list = field(default_factory=list)  # decoded timecode, if any
    run_id: Optional[int] = None
    chunks: list = field(default_factory=list)
    raw_gaps: list = field(default_factory=list)
    verdict: str = ""
    findings: list = field(default_factory=list)

    @property
    def ok(self):
        return bool(self.cls.get("locked"))


@dataclass
class Analysis:
    sources: list = field(default_factory=list)     # file paths
    results: list = field(default_factory=list)     # StreamResult
    pairs: list = field(default_factory=list)       # cross-stream comparisons
    warnings: list = field(default_factory=list)

    def __str__(self):
        L = ["=" * 78,
             "PRE-SYNC FULL ANALYSIS",
             "=" * 78]
        for s in self.sources:
            L.append(f"  source: {os.path.basename(s)}")
        L.append("")
        L.append(_summary_table(self.results))
        for r in self.results:
            L.append("")
            L.append(_stream_block(r))
        if self.pairs:
            L += ["", "-" * 78, "BETWEEN STREAMS", "-" * 78]
            for p in self.pairs:
                L.append(p)
        if self.warnings:
            L += ["", "-" * 78, "WARNINGS", "-" * 78]
            L += [f"  - {w}" for w in self.warnings]
        L.append("=" * 78)
        return "\n".join(L)

    def to_pdf(self, path, title=""):
        return _pdf(self, path, title)


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------

def _summary_table(results):
    hdr = (f"  {'stream':26} {'captured':>9} {'jitter':>9} {'quanta':>8} "
           f"{'on-tick':>8} {'drift':>9} {'outages':>8}")
    L = [hdr, "  " + "-" * (len(hdr) - 2)]
    for r in results:
        if not r.ok:
            L.append(f"  {r.stream.name[:26]:26} {'NOT LOCATED':>9}")
            continue
        c = r.cls
        L.append(f"  {r.stream.name[:26]:26} "
                 f"{100*c['n_captured']/c['n_emitted']:8.1f}% "
                 f"{c['jitter_sd_ms']:8.2f}m {c['jitter_sd_units']:8.3f} "
                 f"{c['within_half_unit_pct']:7.1f}% {c['drift_ppm']:+8.0f}p "
                 f"{len(c['outages']):8d}")
    return "\n".join(L)


def _stream_block(r: StreamResult):
    s, c = r.stream, r.cls
    L = ["-" * 78, f"{s.name}   [{s.kind}]", "-" * 78]
    if s.nominal_rate:
        eff = ""
        if s.n_samples and np.isfinite(s.duration_s) and s.duration_s > 0:
            e = (s.n_samples - 1) / s.duration_s
            eff = (f", delivered {e:.2f} Hz "
                   f"({100*(1-e/s.nominal_rate):+.1f}%)")
        L.append(f"  nominal {s.nominal_rate:g} Hz{eff};  "
                 f"stream {s.duration_s:.1f} s, {s.n_samples} samples")
    if not r.ok:
        L.append(f"  NOT LOCATED — {c.get('note','')}")
        return "\n".join(L)

    L += [f"  located {c.get('start_min', float('nan')):.1f} min into the "
          f"generator's run" if 'start_min' in c else "",
          "",
          f"  CAPTURE    {c['n_captured']}/{c['n_emitted']} emitted "
          f"({100*c['n_captured']/c['n_emitted']:.1f}%)",
          f"  OFFSET     {c['offset_ms']:+.2f} ms          constant — subtract it",
          f"  DRIFT      {c['drift_ppm']:+.0f} ppm = {c['drift_ppm']*60/1000:+.2f} ms/min"
          f" = {c['drift_ppm']*3.6:+.0f} ms/hour   correctable",
          f"  JITTER     sd {c['jitter_sd_ms']:.2f} ms ({c['jitter_sd_units']:.3f} quanta), "
          f"max {c['jitter_max_ms']:.2f} ms ({c['jitter_max_units']:.2f} quanta)",
          f"             {c['within_half_unit_pct']:.1f}% inside half a quantum "
          f"— i.e. on the correct 5 ms tick"]
    if c["n_gross"]:
        at = ", ".join(f"{t:.1f}s({v:+.0f}ms)"
                       for t, v in zip(c["gross_at_s"], c["gross_ms"]))
        L.append(f"  GROSS      {c['n_gross']} corrupt timestamp(s): {at[:70]}")
        L.append(f"             excluded from jitter — single bad values, not spread")
    if c["outages"]:
        L.append(f"  OUTAGES    {len(c['outages'])} event(s), {c['outage_s']:.1f} s, "
                 f"{c['n_outage_missed']} transitions")
        for o in c["outages"]:
            L.append(f"               {o['start_s']:.1f}–{o['end_s']:.1f}s "
                     f"({o['duration_s']:.1f}s, {o['n_missed']} missed)")
    if c["n_isolated"]:
        L.append(f"  ISOLATED   {c['n_isolated']} single miss(es)")
    if r.raw_gaps:
        L.append(f"  RAW GAPS   {len(r.raw_gaps)} interruption(s) in the sample "
                 f"stream itself:")
        for t, ms in r.raw_gaps[:5]:
            L.append(f"               {t:.1f}s  ({ms:.0f} ms)")
    if r.frames:
        L.append(f"  TIMECODE   {len(r.frames)} frame(s) decoded, run ID "
                 f"{r.run_id} — absolute position without a search")
    if r.chunks:
        bad = [i for i, ch in enumerate(r.chunks) if not ch["usable"]]
        L.append(f"  CHUNKS     {len(r.chunks)} analysed, "
                 f"{len(r.chunks)-len(bad)} usable"
                 + (f"; unusable: {bad}" if bad else ""))
    L += ["", f"  VERDICT    {r.verdict}"]
    for f_ in r.findings:
        L.append(f"             - {f_}")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def analyze_streams(streams, chunk_s=10.0) -> Analysis:
    """Full analysis of a set of streams that share the sync signal."""
    A = Analysis()
    for s in streams:
        r = StreamResult(stream=s)
        r.cls = truth.classify(s.times, both_edges=s.both_edges)

        # Timecode frames are a bonus when present: absolute position and run
        # identity with no search, and natural chunk boundaries.
        try:
            fr = tc.decode_frames(sorted(s.times.tolist()),
                                  edge="rising" if not s.both_edges else "rising")
            fr = [f for f in fr if f.get("ok")]
            if fr:
                r.frames = fr
                ids = [f["run_id"] for f in fr]
                r.run_id = max(set(ids), key=ids.count)
        except Exception:
            pass

        # Interruptions in the underlying sample stream, distinct from missing
        # transitions: this says the acquisition itself stalled.
        if s.sample_gaps is not None and s.nominal_rate:
            lim = max(0.05, 5.0 / s.nominal_rate)
            idx = np.flatnonzero(s.sample_gaps > lim)
            t0 = s.stream_start or 0.0
            r.raw_gaps = [(float(np.sum(s.sample_gaps[:i]) ),
                           float(s.sample_gaps[i] * 1000)) for i in idx][:10]

        if r.ok:
            r.chunks = _chunks(r, chunk_s)
            _judge(r)
        else:
            r.verdict = "could not be located in the generator's output"
        A.results.append(r)

    A.pairs = _compare(A.results)
    A.warnings = _collect_warnings(A.results)
    return A


def _chunks(r: StreamResult, chunk_s):
    """Per-chunk quality. Boundaries come from timecode frames when the
    recording carries them, else fixed intervals. Fitting drift per chunk also
    keeps the correction valid over hours, where a warming crystal curves."""
    c = r.cls
    span = c.get("span_s") or 0
    if not span:
        return []
    bounds = ([f["t_rec"] - r.stream.times[0] for f in r.frames]
              if len(r.frames) >= 2
              else list(np.arange(0, span + chunk_s, chunk_s)))
    out = []
    for lo, hi in zip(bounds[:-1], bounds[1:]):
        lost = [t for t in
                [o for oo in c["outages"] for o in
                 np.linspace(oo["start_s"], oo["end_s"], oo["n_missed"])]
                + c["isolated_at_s"] if lo <= t < hi]
        out.append({"start_s": float(lo), "end_s": float(hi),
                    "n_missing": len(lost),
                    "usable": len(lost) == 0})
    return out


def _judge(r: StreamResult):
    c = r.cls
    cap = 100 * c["n_captured"] / max(c["n_emitted"], 1)
    ontick = c["within_half_unit_pct"]
    f = r.findings

    if c["outages"]:
        tot = c["outage_s"]
        f.append(f"{len(c['outages'])} outage(s) totalling {tot:.1f} s — the "
                 f"stream stopped, so this is lost data rather than poor "
                 f"timing, and no correction recovers it.")
    if c["n_gross"]:
        f.append(f"{c['n_gross']} individual corrupt timestamp(s), excluded "
                 f"from the jitter figure. Without excluding them the "
                 f"apparent jitter would be several times larger.")
    if abs(c["drift_ppm"]) > 20:
        f.append(f"Clock differs by {c['drift_ppm']:+.0f} ppm — "
                 f"{c['drift_ppm']*3.6:+.0f} ms over an hour. Remove it with the "
                 f"fitted rate; acquisition software cannot see this on its own.")
    if ontick < 95:
        f.append(f"Only {ontick:.1f}% of transitions land within half a quantum, "
                 f"so {100-ontick:.1f}% would be assigned to the wrong 5 ms tick.")

    if ontick >= 99 and not c["outages"] and cap > 98:
        r.verdict = (f"CLEAN — {c['jitter_sd_units']:.3f} quanta, everything on "
                     f"the correct tick, nothing lost")
    elif ontick >= 95 and not c["outages"]:
        r.verdict = (f"GOOD — {c['jitter_sd_units']:.3f} quanta, "
                     f"{cap:.1f}% captured")
    elif c["outages"] and ontick >= 95:
        r.verdict = (f"WELL TIMED BUT INTERRUPTED — timing is "
                     f"{c['jitter_sd_units']:.3f} quanta, but {c['outage_s']:.1f} s "
                     f"of data is missing")
    elif ontick < 95 and not c["outages"]:
        r.verdict = (f"IMPRECISE — {100-ontick:.1f}% off-tick at the generator's "
                     f"own resolution")
    else:
        r.verdict = (f"DEGRADED — {100-ontick:.1f}% off-tick and "
                     f"{c['outage_s']:.1f} s missing")


def _compare(results):
    """Differences between streams. Each was scored against the generator
    independently, so a difference is attributable to the stream rather than
    to whichever was picked as a reference."""
    ok = [r for r in results if r.ok]
    if len(ok) < 2:
        return []
    base = min(ok, key=lambda r: r.cls["jitter_sd_units"])
    out = [f"  reference: {base.stream.name} (lowest jitter)"]
    for r in ok:
        if r is base:
            continue
        c, b = r.cls, base.cls
        out.append(f"    {r.stream.name[:28]:28} "
                   f"lag {c['offset_ms']-b['offset_ms']:+7.2f} ms   "
                   f"drift {c['drift_ppm']-b['drift_ppm']:+7.0f} ppm   "
                   f"jitter {c['jitter_sd_ms']:.2f} vs {b['jitter_sd_ms']:.2f} ms "
                   f"({c['jitter_sd_ms']/max(b['jitter_sd_ms'],1e-9):.1f}x)")
    # Outages shared between streams point upstream of any one device.
    spans = {r.stream.name: [(o["start_s"], o["end_s"]) for o in r.cls["outages"]]
             for r in ok}
    names = list(spans)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            for a in spans[names[i]]:
                for b in spans[names[j]]:
                    if not (a[1] < b[0] - 2 or a[0] > b[1] + 2):
                        out.append(
                            f"    SHARED OUTAGE {max(a[0],b[0]):.1f}–"
                            f"{min(a[1],b[1]):.1f}s in both {names[i][:18]} and "
                            f"{names[j][:18]} — a fault common to both, so it "
                            f"lies upstream of either device.")
    return out


def _collect_warnings(results):
    w = []
    for r in results:
        if not r.ok:
            w.append(f"{r.stream.name}: {r.cls.get('note','not located')}")
    return w


# ---------------------------------------------------------------------------
# XDF loading
# ---------------------------------------------------------------------------

def load_xdf(path, verbose=False):
    """Every sync-bearing stream in an XDF file."""
    import pyxdf
    streams, _ = pyxdf.load_xdf(path, dejitter_timestamps=False,
                                synchronize_clocks=False)
    out = []
    for s in streams:
        info = s["info"]
        name = info["name"][0]
        ts = np.asarray(s["time_stamps"], float)
        d = np.asarray(s["time_series"])
        if d.dtype.kind not in "fiu" or d.ndim != 2 or len(ts) < 20:
            continue
        labels = []
        try:
            labels = [c["label"][0] for c in
                      info["desc"][0]["channels"][0]["channel"]]
        except Exception:
            pass
        clk = None
        try:
            v = [float(x["value"][0]) for x in
                 s["footer"]["info"]["clock_offsets"][0]["offset"]]
            if v:
                clk = float(np.median(v))
        except Exception:
            pass

        best = None
        for ci in range(d.shape[1]):
            col = d[:, ci].astype(float)
            if not np.isfinite(col).all() or col.std() == 0:
                continue
            lab = labels[ci] if ci < len(labels) else f"ch{ci}"
            lo, hi = col.min(), col.max()
            mid = (lo + hi) / 2
            up = np.flatnonzero((col[1:] > mid) & (col[:-1] <= mid)) + 1
            dn = np.flatnonzero((col[1:] <= mid) & (col[:-1] > mid)) + 1
            if len(up) < 5:
                continue
            is_trig = "trig" in lab.lower()
            # A trigger line pulses briefly, so only its rises are events; an
            # analog channel carries the whole wave, so both edges are real
            # and using rises alone doubles every interval.
            times = ts[up] if is_trig else ts[np.sort(np.concatenate([up, dn]))]
            frac_ext = np.mean((col < lo + 0.1*(hi-lo)) | (col > hi - 0.1*(hi-lo)))
            score_ = frac_ext + (1.0 if is_trig else 0.0)
            if best is None or score_ > best[0]:
                best = (score_, lab, times, is_trig)
        if best is None:
            continue
        _, lab, times, is_trig = best
        if clk is not None:
            times = times + clk
        out.append(Stream(
            name=f"{name}::{lab}", times=times, both_edges=not is_trig,
            kind="trigger events" if is_trig else "analog sync",
            nominal_rate=float(info["nominal_srate"][0] or 0) or None,
            n_samples=len(ts),
            stream_start=float(ts[0]), stream_end=float(ts[-1]),
            clock_offset=clk, sample_gaps=np.diff(ts)))
        if verbose:
            print(f"  {name}::{lab}  {len(times)} transitions")
    return out


def analyze_file(*paths, chunk_s=10.0, verbose=False) -> Analysis:
    streams = []
    origin = {}
    for p in paths:
        got = load_xdf(p, verbose=verbose)
        for g in got:
            origin[id(g)] = p
        streams += got
    A = analyze_streams(streams, chunk_s=chunk_s)
    for r in A.results:
        r.source = origin.get(id(r.stream), "")
    A.sources = list(paths)
    return A


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------

def _pdf(A: Analysis, path, title=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_pdf import PdfPages
    import textwrap

    ok = [r for r in A.results if r.ok]
    with PdfPages(path) as pdf:
        # ---- page 1: the report text ------------------------------------
        fig = plt.figure(figsize=(8.5, 11))
        fig.suptitle(title or "PRE-Sync analysis", fontsize=13, y=0.985)
        ax = fig.add_axes([0.04, 0.02, 0.92, 0.93]); ax.axis("off")
        body = []
        for line in str(A).splitlines():
            body += (textwrap.wrap(line, 112, subsequent_indent="       ")
                     if len(line) > 112 else [line])
        ax.text(0, 1, "\n".join(body[:96]), family="monospace", fontsize=5.4,
                va="top")
        pdf.savefig(fig); plt.close(fig)
        if len(body) > 96:
            fig = plt.figure(figsize=(8.5, 11)); ax = fig.add_axes([0.04,0.02,0.92,0.95])
            ax.axis("off")
            ax.text(0, 1, "\n".join(body[96:]), family="monospace", fontsize=5.4, va="top")
            pdf.savefig(fig); plt.close(fig)

        if not ok:
            return path

        # ---- page 2: plots ----------------------------------------------
        cols = plt.cm.tab10(np.linspace(0, 1, 10))
        fig, axes = plt.subplots(4, 1, figsize=(8.5, 11),
                                 gridspec_kw={"hspace": 0.55})
        fig.suptitle("Timing against the emitted waveform", fontsize=12, y=0.975)

        def _lbl(r):
            base = r.stream.name.split('::')[0].split('_on_')[0][:14]
            src = ''
            if r.source:
                b = os.path.basename(r.source).lower()
                for k in ('wireless', 'wired'):
                    if k in b:
                        src = f'\n{k}'; break
            return base + src

        ax = axes[0]
        for i, r in enumerate(ok):
            c = r.cls
            t = np.asarray(c.get("_t", []), float)
            ax.plot([], [])
        # residuals are recomputed here so the plot matches the report exactly
        for i, r in enumerate(ok):
            res, tt = _residuals(r)
            if res is None:
                continue
            ax.plot(tt, res / STEP_MS, ".", ms=3.5, color=cols[i % 10],
                    label=f"{_lbl(r).replace(chr(10),' ')} "
                          f"({r.cls['jitter_sd_units']:.3f} q)")
            for o in r.cls["outages"]:
                ax.axvspan(o["start_s"], o["end_s"], color=cols[i % 10], alpha=0.13)
        ax.axhline(0.5, color="0.4", ls=":", lw=.9)
        ax.axhline(-0.5, color="0.4", ls=":", lw=.9)
        ax.set_ylabel("error (quanta)")
        ax.set_title("Jitter after removing offset and drift. Dotted lines = half a "
                     "quantum;\ninside them a transition is on the correct 5 ms tick. "
                     "Shading = outages.", fontsize=8)
        ax.legend(fontsize=6, ncol=2); ax.grid(alpha=.3)

        ax = axes[1]
        # Two files commonly contribute streams with identical names (the
        # same Kinarm in both sessions), so the source has to be part of the
        # label or the bars are unreadable.
        def _lbl(r):
            base = r.stream.name.split("::")[0]
            base = base.split("_on_")[0][:14]
            src = ""
            if r.source:
                b = os.path.basename(r.source).lower()
                for k in ("wireless", "wired"):
                    if k in b:
                        src = f"\n{k}"; break
            return base + src
        names = [_lbl(r) for r in ok]
        x = np.arange(len(ok))
        ax.bar(x, [r.cls["within_half_unit_pct"] for r in ok],
               color=[cols[i % 10] for i in range(len(ok))], alpha=.85)
        ax.axhline(95, color="r", ls="--", lw=.9, label="95%")
        ax.set_xticks(x); ax.set_xticklabels(names, fontsize=7, rotation=12)
        ax.set_ylabel("% on correct tick"); ax.set_ylim(0, 103)
        for xi, r in zip(x, ok):
            ax.text(xi, r.cls["within_half_unit_pct"] + 1,
                    f"{r.cls['within_half_unit_pct']:.1f}", ha="center", fontsize=7)
        ax.set_title("Fraction of transitions resolvable at the generator's own "
                     "5 ms resolution", fontsize=8)
        ax.legend(fontsize=6); ax.grid(alpha=.3, axis="y")

        ax = axes[2]
        w = 0.36
        ax.bar(x - w/2, [100*r.cls["n_captured"]/r.cls["n_emitted"] for r in ok],
               w, color=[cols[i % 10] for i in range(len(ok))], alpha=.85,
               label="captured %")
        ax.bar(x + w/2, [r.cls["outage_s"] for r in ok], w, alpha=.45,
               color=[cols[i % 10] for i in range(len(ok))], hatch="//",
               label="outage seconds")
        ax.set_xticks(x); ax.set_xticklabels(names, fontsize=7, rotation=12)
        ax.set_title("Data integrity — solid: transitions captured (%), "
                     "hatched: seconds lost to outages", fontsize=8)
        ax.legend(fontsize=6); ax.grid(alpha=.3, axis="y")

        ax = axes[3]
        d = [r.cls["drift_ppm"] for r in ok]
        ax.bar(x, d, color=[cols[i % 10] for i in range(len(ok))], alpha=.85)
        ax.set_xticks(x); ax.set_xticklabels(names, fontsize=7, rotation=12)
        ax.set_ylabel("ppm")
        for xi, v in zip(x, d):
            ax.text(xi, v + np.sign(v)*2, f"{v:+.0f}\n({v*3.6:+.0f} ms/h)",
                    ha="center", fontsize=6.5)
        ax.set_title("Clock drift — multiply by 3.6 for ms per hour.\n"
                     "Correctable, but only if measured.", fontsize=8)
        ax.margins(y=0.22)
        ax.grid(alpha=.3, axis="y")

        pdf.savefig(fig); plt.close(fig)
    return path


def _residuals(r: StreamResult):
    """Recompute per-transition residuals for plotting."""
    s = r.stream
    rep = truth.score(s.times, both_edges=s.both_edges)
    if not rep.locked:
        return None, None
    T = truth._template(s.both_edges)
    pred = s.times - rep._lock_off
    tr = T[(T >= pred[0]) & (T <= pred[-1])]
    if not len(tr):
        return None, None
    t0 = tr[0]
    m, e = [], []
    for x in tr:
        j = int(np.argmin(np.abs(pred - x)))
        if abs(pred[j] - x) < truth.MATCH_WINDOW_S:
            m.append(x - t0); e.append((pred[j] - x) * 1000)
    m = np.asarray(m); e = np.asarray(e)
    if len(m) < 3:
        return None, None
    sl, ic = np.polyfit(m, e / 1000, 1)
    return (e / 1000 - (sl * m + ic)) * 1000, m


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(
        description="Full PRE-Sync analysis of one or more recordings.")
    ap.add_argument("files", nargs="+", help="XDF file(s)")
    ap.add_argument("--pdf", help="write the report here")
    ap.add_argument("--chunk", type=float, default=10.0,
                    help="chunk length in seconds (default 10)")
    a = ap.parse_args(argv)

    A = analyze_file(*a.files, chunk_s=a.chunk, verbose=True)
    print(A)
    if a.pdf:
        A.to_pdf(a.pdf)
        print(f"\nwrote {a.pdf}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

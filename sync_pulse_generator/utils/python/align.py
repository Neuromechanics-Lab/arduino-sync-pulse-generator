#!/usr/bin/env python3
"""
align.py - Align any number of recordings onto one timeline.

The problem: several devices record the same experiment, each with its own
clock, its own start time, its own sample rate, and its own way of reporting
the sync signal — one gives you a continuous analog waveform, another gives
you only the timestamps of rising edges, a third only falling edges. Some
drop frames. None of them agree on when zero was.

The approach: do NOT align recordings to each other. The generator's output
is fully determined by (seed, config), so `timecode.generate_template()`
reproduces the exact intended waveform. Every recording is locked
INDEPENDENTLY to that template, which makes alignment transitive: any two
recordings are related through the template, with no reference device, no
pairwise matrix, and no error accumulation. Devices whose recordings never
overlap in wall-clock time still land on one timeline.

Why it works for edge-only inputs: the template is a list of transition
times, and a rising-edge-only recording is also a list of transition times.
Same object, same matching. A continuous signal just passes through
detect_edges first to become one.

Why it survives dropped frames: each edge is matched to the template
independently rather than sequentially, so a missing edge is an unmatched
template entry, not a cascade that corrupts everything after it.

Three output modes:
    'lags'         numbers only — offset, clock rate, drops, confidence
    'global_time'  each recording keeps its own samples and rate, and gains
                   a global_time column. Nothing resampled, nothing lost.
    'stitch'       one merged table on a common time base

Usage:
    from align import Source, align_recordings

    srcs = [
        Source.from_continuous('vicon', vicon_sync, fs=1000, data=vicon_df),
        Source.from_edges('eeg', rising_times, polarity='rising'),
        Source.from_continuous('daq', daq_sync, fs=2048),
    ]
    res = align_recordings(srcs, mode='global_time')

Dependencies: numpy. Uses edge_sync for continuous-signal edge detection.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Optional, Sequence, Union

import numpy as np

import timecode as tc

try:
    from edge_sync import detect_edges
    HAVE_EDGE_SYNC = True
except ImportError:                                      # pragma: no cover
    HAVE_EDGE_SYNC = False


# Firmware defaults (config.h). The generator config is fixed for this lab,
# so the template is reproducible without per-recording metadata.
SEED = 42
MIN_HIGH_MS = 50
MAX_HIGH_MS = 500
MIN_LOW_MS = 50
MAX_LOW_MS = 500
TC_ENABLED = True
TC_INTERVAL_S = 10

# Intervals shorter than this belong to a timecode frame, not the
# pseudo-random train. They are excluded from fingerprint matching.
#
# This threshold is load-bearing. Frame internals are 5/15/25 ms pulses drawn
# from a tiny alphabet, and in a one-hour template they are 77% of all
# transitions. Including them makes the fingerprint hopelessly ambiguous
# (~75% of windows match somewhere else); excluding them makes a window of
# only 4 intervals unique across the entire hour. The pseudo-random minimum
# is 50 ms, so 45 ms separates the two populations with margin.
PR_MIN_INTERVAL_S = 0.045

# Fingerprint window length, in pseudo-random intervals. Measured on a 1-hour
# template: k=4 gave 0/200 ambiguous windows, and 100/100 unique locks from
# rising-edges-only with 1 ms jitter. Longer is NOT better — a longer window
# is more likely to span a dropped edge, and one bad interval kills it.
FINGERPRINT_K = 4

# Matching tolerance for a single interval, seconds. Must exceed the
# recorder's timing jitter but stay below the 5 ms duration quantum.
INTERVAL_TOL_S = 0.006

# A lock needs at least this many agreeing windows.
MIN_VOTES = 3


# ---------------------------------------------------------------------------
# Input
# ---------------------------------------------------------------------------

@dataclass
class Source:
    """One recording's sync evidence, plus optionally its data.

    Build with from_continuous() or from_edges() rather than directly.
    """
    name: str
    edge_times: np.ndarray            # seconds, in this recording's own clock
    polarity: Optional[np.ndarray] = None   # +1/-1 per edge, None if unknown
    kind: str = "edges"               # 'continuous' | 'edges'
    fs: Optional[float] = None        # nominal rate, if the source has one
    data: Optional[np.ndarray] = None       # samples x channels
    labels: Optional[list] = None
    time: Optional[np.ndarray] = None       # per-sample times, own clock

    @classmethod
    def from_continuous(cls, name, signal, fs, data=None, labels=None,
                        time=None, **detect_kw):
        """A recorded analog copy of the square wave."""
        if not HAVE_EDGE_SYNC:
            raise ImportError("edge_sync is required for continuous sources.")
        e = detect_edges(np.asarray(signal, float), fs, **detect_kw)
        return cls(name=name, edge_times=np.asarray(e.time, float),
                   polarity=np.asarray(e.polarity, int), kind="continuous",
                   fs=fs, data=data, labels=labels, time=time)

    @classmethod
    def from_edges(cls, name, edge_times, polarity="both", fs=None,
                   data=None, labels=None, time=None):
        """Transition timestamps only — the case where a device reports
        events rather than a waveform.

        polarity: 'rising', 'falling', 'both', or an array of +1/-1.

        A rising-only or falling-only stream aligns just as well as a full
        one: the fingerprint is built from the gaps between the edges you
        did record, and those gaps are still drawn from the pseudo-random
        sequence.
        """
        t = np.asarray(edge_times, float).ravel()
        t = np.sort(t)
        if isinstance(polarity, str):
            pol = {"rising": np.ones(t.size, int),
                   "falling": -np.ones(t.size, int),
                   "both": None}.get(polarity)
            if polarity not in ("rising", "falling", "both"):
                raise ValueError("polarity must be 'rising', 'falling', "
                                 "'both', or an array")
        else:
            pol = np.asarray(polarity, int).ravel()
            if pol.size != t.size:
                raise ValueError("polarity array must match edge_times length")
        return cls(name=name, edge_times=t, polarity=pol, kind="edges",
                   fs=fs, data=data, labels=labels, time=time)

    def sample_times(self) -> np.ndarray:
        """Per-sample times in this recording's own clock."""
        if self.time is not None:
            return np.asarray(self.time, float)
        if self.data is None:
            return np.empty(0)
        if self.fs is None:
            raise ValueError(f"{self.name}: needs fs or an explicit time vector")
        return np.arange(np.shape(self.data)[0]) / self.fs


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class Fit:
    """How one recording maps onto template (global) time."""
    name: str
    ok: bool
    offset_s: float = float("nan")       # global = offset + rate * local
    rate: float = float("nan")           # 1.0 means clocks agree
    drift_ppm: float = float("nan")
    n_edges: int = 0
    n_matched: int = 0
    match_rate: float = 0.0
    residual_ms: float = float("nan")    # worst |residual| after the fit
    rms_ms: float = float("nan")
    confidence: float = 0.0              # winning votes / total votes
    drops: list = field(default_factory=list)   # (local_time, step_ms)
    segments: list = field(default_factory=list)  # (t0,t1,offset,rate) per span
    run_id: Optional[int] = None
    frames: list = field(default_factory=list)  # decoded (t_rec, elapsed_s)
    source_of_lock: str = ""     # 'timecode' or 'fingerprint'
    note: str = ""

    def to_global(self, t_local):
        """Local clock -> global (template) time.

        Piecewise when the recording dropped frames: each continuous segment
        carries its own offset, because a drop shifts everything after it.
        Times inside the dropped span map with the nearest segment, since no
        samples actually exist there.
        """
        t = np.asarray(t_local, float)
        if not self.segments:
            return self.offset_s + self.rate * t
        out = np.empty_like(t, dtype=float)
        starts = np.array([sg[0] for sg in self.segments])
        which = np.clip(np.searchsorted(starts, t, side="right") - 1,
                        0, len(self.segments) - 1)
        for k, sg in enumerate(self.segments):
            m = which == k
            if m.any():
                out[m] = sg[2] + sg[3] * t[m]
        return out

    def to_local(self, t_global):
        g = np.asarray(t_global, float)
        if not self.segments:
            return (g - self.offset_s) / self.rate
        out = np.empty_like(g, dtype=float)
        gstarts = np.array([sg[2] + sg[3] * sg[0] for sg in self.segments])
        which = np.clip(np.searchsorted(gstarts, g, side="right") - 1,
                        0, len(self.segments) - 1)
        for k, sg in enumerate(self.segments):
            m = which == k
            if m.any():
                out[m] = (g[m] - sg[2]) / sg[3]
        return out

    def __str__(self):
        if not self.ok:
            return f"{self.name:12s} FAILED — {self.note}"
        drift = f"{self.drift_ppm:+.0f} ppm"
        drops = f", {len(self.drops)} drop(s)" if self.drops else ""
        return (f"{self.name:12s} offset {self.offset_s:+9.4f} s  {drift:>10}  "
                f"matched {self.n_matched}/{self.n_edges} "
                f"({100*self.match_rate:.0f}%)  rms {self.rms_ms:.2f} ms{drops}")


@dataclass
class AlignResult:
    """What align_recordings returns."""
    mode: str
    fits: list
    sources: list
    global_time: dict = field(default_factory=dict)   # name -> np.ndarray
    table: Optional[dict] = None      # stitch: {'time': .., 'columns': {...}}
    warnings: list = field(default_factory=list)

    def __str__(self):
        out = [f"align_recordings(mode={self.mode!r})", ""]
        out += [str(f) for f in self.fits]
        if self.warnings:
            out += ["", "Warnings:"] + [f"  - {w}" for w in self.warnings]
        return "\n".join(out)

    def lag_between(self, a: str, b: str) -> float:
        """Seconds by which b lags a, from their fits against the template."""
        fa = next(f for f in self.fits if f.name == a)
        fb = next(f for f in self.fits if f.name == b)
        if not (fa.ok and fb.ok):
            return float("nan")
        return fb.offset_s - fa.offset_s


# ---------------------------------------------------------------------------
# Template
# ---------------------------------------------------------------------------

_TEMPLATE_CACHE: dict = {}


def build_template(duration_s: float, run_id: int = 1) -> dict:
    """Edge times of the intended signal, from code rather than a recording."""
    key = (round(duration_s), run_id)
    if key in _TEMPLATE_CACHE:
        return _TEMPLATE_CACHE[key]

    times, levels = tc.generate_template(
        seed=SEED, duration_s=duration_s,
        min_high=MIN_HIGH_MS, max_high=MAX_HIGH_MS,
        min_low=MIN_LOW_MS, max_low=MAX_LOW_MS,
        tc_enabled=TC_ENABLED, tc_interval_s=TC_INTERVAL_S, run_id=run_id)

    t = np.asarray(times, float) / 1000.0
    lv = np.asarray(levels, int)
    pol = np.where(lv == 1, 1, -1)

    tmpl = {"time": t, "polarity": pol}
    for name, sel in (("both", slice(None)),
                      ("rising", pol > 0),
                      ("falling", pol < 0)):
        et = t[sel]
        iv = np.diff(et)
        keep = iv >= PR_MIN_INTERVAL_S
        tmpl[name] = {
            "edges": et,
            "iv": iv[keep],
            "pos": np.flatnonzero(keep),      # index into et of each kept iv
        }
        if len(iv[keep]) >= FINGERPRINT_K:
            tmpl[name]["win"] = np.lib.stride_tricks.sliding_window_view(
                iv[keep], FINGERPRINT_K)
        else:
            tmpl[name]["win"] = np.empty((0, FINGERPRINT_K))

    _TEMPLATE_CACHE[key] = tmpl
    return tmpl


def _pr_intervals(edges: np.ndarray):
    """Pseudo-random intervals and the index of each one's first edge.

    Frame-internal intervals are dropped: they are short, repetitive, and
    would swamp the fingerprint. See PR_MIN_INTERVAL_S.
    """
    if edges.size < 2:
        return np.empty(0), np.empty(0, int)
    iv = np.diff(edges)
    keep = iv >= PR_MIN_INTERVAL_S
    return iv[keep], np.flatnonzero(keep)


# ---------------------------------------------------------------------------
# Locking a recording to the template
# ---------------------------------------------------------------------------

def decode_source_frames(src: Source):
    """Read the binary timecode frames a recording carries, if any.

    A frame is 52 bits of pulse timing: [16-bit run ID][32-bit elapsed
    seconds][4-bit checksum]. Where one survives it beats any fingerprint —
    it states the position outright, checksum-verified, and it is the ONLY
    thing that identifies WHICH RUN was recorded, since a fixed seed makes
    every run's waveform identical.

    The decoder needs a single-polarity edge stream: frame pulses have
    constant width, so rising-only and falling-only both decode, but an
    interleaved both-edges list halves every interval and decodes nothing.
    Each polarity present is therefore tried separately.

    Returns (frames, run_id) with only checksum-valid frames.
    """
    t = np.asarray(src.edge_times, float)
    if t.size < 55:                      # a whole frame is 55 pulses
        return [], None

    tries = []
    if src.polarity is None:
        tries.append((t, "rising"))
        tries.append((t, "falling"))
    else:
        if np.any(src.polarity > 0):
            tries.append((t[src.polarity > 0], "rising"))
        if np.any(src.polarity < 0):
            tries.append((t[src.polarity < 0], "falling"))

    best = []
    for edges, edge_kind in tries:
        if edges.size < 55:
            continue
        try:
            got = tc.decode_frames(sorted(edges.tolist()), edge=edge_kind)
        except Exception:
            continue
        ok = [f for f in got if f.get("ok")]
        if len(ok) > len(best):
            best = ok

    if not best:
        return [], None
    ids = [f["run_id"] for f in best]
    run_id = max(set(ids), key=ids.count)
    return best, run_id


def _which_stream(src: Source) -> str:
    """Whether to match against the template's rising, falling, or all edges."""
    if src.polarity is None:
        return "both"
    if np.all(src.polarity > 0):
        return "rising"
    if np.all(src.polarity < 0):
        return "falling"
    return "both"


def _vote_lock(probe_iv, probe_pos, tmpl, tol=INTERVAL_TOL_S,
               k=FINGERPRINT_K, max_windows=60):
    """Coarse alignment by voting across many short interval windows.

    Each window of k consecutive intervals proposes an edge-index offset
    between probe and template. The true offset is proposed by every clean
    window; a window spanning a dropped edge proposes noise. Taking the
    plurality therefore tolerates a substantial fraction of bad windows —
    measured: 100% lock up to 20% dropped edges, degrading gracefully to
    ~22% at 50% dropped.

    Voting is used rather than one long window because a longer window is
    MORE likely to contain a drop, not less: at 10% dropout a k=8 window
    found a lock only 39% of the time against k=4's 66%.
    """
    W = tmpl["win"]
    if W.shape[0] == 0 or len(probe_iv) < k:
        return None, 0, 0

    votes = Counter()
    n = min(max_windows, len(probe_iv) - k + 1)
    step = max(1, (len(probe_iv) - k + 1) // n) if n else 1

    for w in range(0, len(probe_iv) - k + 1, step):
        d = np.max(np.abs(W - probe_iv[w:w + k]), axis=1)
        for c in np.flatnonzero(d < tol):
            votes[int(tmpl["pos"][c] - probe_pos[w])] += 1

    if not votes:
        return None, 0, 0
    best, score = votes.most_common(1)[0]
    return best, score, sum(votes.values())


def _pair_edges(src_edges, tmpl_edges, shift, tol_s):
    """Nearest-neighbour pairing after the coarse lock.

    Pairs by TIME rather than by index, so a dropped edge costs one pair
    instead of desynchronising everything downstream.
    """
    lo = max(0, shift)
    if lo >= len(tmpl_edges):
        return np.empty(0), np.empty(0)

    # Coarse alignment implied by the index shift.
    j = np.clip(np.arange(len(src_edges)) + shift, 0, len(tmpl_edges) - 1)
    approx = tmpl_edges[j] - src_edges
    t0 = float(np.median(approx))

    pairs_src, pairs_tmpl = [], []
    idx = np.searchsorted(tmpl_edges, src_edges + t0)
    for i, s in enumerate(src_edges):
        target = s + t0
        for cand in (idx[i] - 1, idx[i], idx[i] + 1):
            if 0 <= cand < len(tmpl_edges):
                if abs(tmpl_edges[cand] - target) <= tol_s:
                    pairs_src.append(s)
                    pairs_tmpl.append(tmpl_edges[cand])
                    break
    return np.asarray(pairs_src), np.asarray(pairs_tmpl)


def _pair_predicted(src_edges, tmpl_edges, offset, rate, tol_s):
    """Pair using the current time map to predict where each edge should land.

    Unlike the coarse pass this follows clock drift and post-drop shifts,
    because the prediction already includes them.
    """
    pred = offset + rate * src_edges
    idx = np.searchsorted(tmpl_edges, pred)
    ps, pt = [], []
    for i, s in enumerate(src_edges):
        best, bestd = None, tol_s
        for cand in (idx[i] - 1, idx[i], idx[i] + 1):
            if 0 <= cand < len(tmpl_edges):
                d = abs(tmpl_edges[cand] - pred[i])
                if d <= bestd:
                    best, bestd = cand, d
        if best is not None:
            ps.append(s)
            pt.append(tmpl_edges[best])
    return np.asarray(ps), np.asarray(pt)


def _pair_at(src_edges, predicted, tmpl_edges, tol_s):
    """Pair each source edge with the template edge nearest its prediction."""
    idx = np.searchsorted(tmpl_edges, predicted)
    ps, pt = [], []
    for i in range(len(src_edges)):
        best, bestd = None, tol_s
        for cand in (idx[i] - 1, idx[i], idx[i] + 1):
            if 0 <= cand < len(tmpl_edges):
                d = abs(tmpl_edges[cand] - predicted[i])
                if d <= bestd:
                    best, bestd = cand, d
        if best is not None:
            ps.append(src_edges[i]); pt.append(tmpl_edges[best])
    return np.asarray(ps), np.asarray(pt)


def _fit_time_map(src_t, tmpl_t, drop_threshold_ms=5.0):
    """Least-squares template_time = offset + rate * local_time.

    Returns (offset, rate, drops, rms_ms, worst_ms) for a SINGLE linear
    segment. Recordings with dropped frames need _fit_segments instead — a
    lone line cannot describe them, and forcing one makes the fit settle on
    whichever side holds more edges while stranding the other.
    """
    if len(src_t) < 2:
        return float("nan"), float("nan"), [], float("nan"), float("nan")

    A = np.vstack([src_t, np.ones_like(src_t)]).T
    rate, offset = np.linalg.lstsq(A, tmpl_t, rcond=None)[0]
    resid = tmpl_t - (rate * src_t + offset)

    # Drop detection lives in _find_breaks, which tests for a SUSTAINED shift.
    # Doing it here on short running medians produced dozens of phantom drops
    # on clean recordings.
    drops = []

    rms = float(np.sqrt(np.mean(resid ** 2)) * 1000)
    worst = float(np.max(np.abs(resid)) * 1000)
    return float(offset), float(rate), drops, rms, worst


def _find_breaks(src_t, tmpl_t, step_thr_s=0.010, min_seg=30):
    """Local times where the recording's timeline STEPS.

    A dropped block only matters when the device's timestamps are derived
    from a sample counter: the counter falls behind, so every later sample is
    labelled earlier than it happened and the mapping to template time jumps.
    Devices with honest wall-clock timestamps just leave a hole, which needs
    no break at all.

    Detection works on the residual against a robust global line, not on
    interval differences. A step is a sustained level change in the residual;
    ordinary missing edges and jitter are not. Requiring the shift to persist
    over `min_seg` pairs on BOTH sides is what separates the two — an earlier
    version compared short running medians and manufactured dozens of
    phantom drops on clean data.
    """
    n = len(src_t)
    if n < 4 * min_seg:
        return []

    # Robust global line: fit on the middle 80% to resist end effects.
    lo, hi = int(0.1 * n), int(0.9 * n)
    A = np.vstack([src_t[lo:hi], np.ones(hi - lo)]).T
    rate, offset = np.linalg.lstsq(A, tmpl_t[lo:hi], rcond=None)[0]
    resid = tmpl_t - (rate * src_t + offset)

    scale = 1.4826 * np.median(np.abs(resid - np.median(resid)))
    thr = max(step_thr_s, 6 * scale)

    breaks = []
    i = min_seg
    while i < n - min_seg:
        before = np.median(resid[i - min_seg:i])
        after = np.median(resid[i:i + min_seg])
        if abs(after - before) > thr:
            breaks.append(int(i))
            i += min_seg          # do not re-trigger on the same step
        else:
            i += 1
    return breaks


def _fit_segments(src_t, tmpl_t, step_thr_s=0.010, min_seg=30):
    """Piecewise-linear time map: one (offset, rate) per continuous segment.

    Returns (segments, drops, rms_ms, worst_ms); segments are
    (start_local, end_local, offset, rate). With no breaks this is a single
    segment and behaves exactly like the plain linear fit.
    """
    breaks = _find_breaks(src_t, tmpl_t, step_thr_s, min_seg)
    bounds = [0] + breaks + [len(src_t)]

    segments, drops, resid_all = [], [], []
    for a, b in zip(bounds[:-1], bounds[1:]):
        st, tt = src_t[a:b], tmpl_t[a:b]
        if len(st) < 2:
            continue
        A = np.vstack([st, np.ones_like(st)]).T
        rate, offset = np.linalg.lstsq(A, tt, rcond=None)[0]
        segments.append((float(st[0]), float(st[-1]), float(offset), float(rate)))
        resid_all.append(tt - (rate * st + offset))

    for k, idx in enumerate(breaks):
        if k + 1 < len(segments):
            step = (segments[k + 1][2] - segments[k][2]) * 1000
            drops.append((float(src_t[idx]), float(step)))

    if resid_all:
        r = np.concatenate(resid_all)
        rms = float(np.sqrt(np.mean(r ** 2)) * 1000)
        worst = float(np.max(np.abs(r)) * 1000)
    else:
        rms = worst = float("nan")
    return segments, drops, rms, worst


ANCHOR_WINDOW_EDGES = 60     # pseudo-random intervals per local lock
ANCHOR_STRIDE_EDGES = 30     # overlap so a bad window cannot hide a step
ANCHOR_MIN_CONF = 0.85       # a window straddling a gap self-reports low
STEP_THRESHOLD_S = 0.010     # offset jump that counts as a lost-count step


def _anchors(src_edges, sub, tol_s):
    """Lock in local windows across the recording, independently.

    Each window yields one (local_time, template_time, confidence) anchor.
    This replaces the earlier approach of guessing a single global shift and
    then trying to force every edge into a fixed tolerance around it: at
    300 ppm the alignment slides ~57 ms over three minutes, so a global
    guess cannot hold, and patching it with rate pre-estimates and step
    detectors kept breaking neighbouring cases.

    Local locks have no such assumption. Offset, clock rate, and lost-count
    steps are all simply read off the resulting anchor series afterwards.
    A window that straddles missing data self-reports low confidence
    (measured: 0.60 against 1.00 for clean windows), so it is filtered
    rather than special-cased.
    """
    piv, ppos = _pr_intervals(src_edges)
    out = []
    w = 0
    while w + ANCHOR_WINDOW_EDGES <= len(piv):
        sl = slice(w, w + ANCHOR_WINDOW_EDGES)
        sh, score, total = _vote_lock(piv[sl], ppos[sl], sub, tol=tol_s,
                                      max_windows=ANCHOR_WINDOW_EDGES)
        if sh is not None and score >= MIN_VOTES and total:
            i = ppos[w]
            j = i + sh
            if 0 <= i < len(src_edges) and 0 <= j < len(sub["edges"]):
                out.append((src_edges[i], sub["edges"][j], score / total))
        w += ANCHOR_STRIDE_EDGES

    # A short recording gets one window over everything it has.
    if not out and len(piv) >= FINGERPRINT_K:
        sh, score, total = _vote_lock(piv, ppos, sub, tol=tol_s)
        if sh is not None and score >= MIN_VOTES and total:
            i, j = ppos[0], ppos[0] + sh
            if 0 <= j < len(sub["edges"]):
                out.append((src_edges[i], sub["edges"][j], score / max(total, 1)))

    return np.array(out) if out else np.empty((0, 3))


def lock_source(src: Source, tmpl: dict, tol_s: float = INTERVAL_TOL_S) -> Fit:
    """Place one recording on the template timeline."""
    fit = Fit(name=src.name, ok=False, n_edges=int(src.edge_times.size))

    if src.edge_times.size < FINGERPRINT_K + 1:
        fit.note = (f"only {src.edge_times.size} edges; need at least "
                    f"{FINGERPRINT_K + 1}")
        return fit

    stream = _which_stream(src)
    sub = tmpl[stream]
    src_edges = src.edge_times

    probe_iv, _ = _pr_intervals(src_edges)
    if len(probe_iv) < FINGERPRINT_K:
        fit.note = (f"only {len(probe_iv)} pseudo-random intervals "
                    f"(>= {PR_MIN_INTERVAL_S*1000:.0f} ms); the recording may be "
                    f"too short, or all its edges fall inside timecode frames")
        return fit

    # Prefer the binary timecode frames when the recording carries them.
    # A decoded frame states its elapsed second outright and is checksum
    # verified, so it beats a fingerprint search: no ambiguity, no template
    # comparison, and it is the only evidence of WHICH RUN this is.
    frames, run_id = decode_source_frames(src)
    fit.frames = [(f["t_rec"], f["elapsed_s"]) for f in frames]
    fit.run_id = run_id

    A = np.empty((0, 3))
    if len(frames) >= 2:
        fa = np.array([[f["t_rec"], float(f["elapsed_s"]), 1.0]
                       for f in frames])
        # Frames land exactly on the interval tick (the firmware holds LOW
        # through a lead-in), so each is an exact anchor, not an approximate
        # one. Confidence 1.0 reflects the checksum, not a vote.
        A = fa
        fit.source_of_lock = "timecode"

    if len(A) < 2:
        A = _anchors(src_edges, sub, tol_s)
        fit.source_of_lock = "fingerprint"

    if len(A) == 0:
        fit.note = ("could not lock to the template. Check that the seed and "
                    "timing config match the firmware that produced this "
                    "recording, and that the sync channel is the right one.")
        return fit

    fit.confidence = float(np.median(A[:, 2]))
    good = A[A[:, 2] >= ANCHOR_MIN_CONF]
    if len(good) < 1:
        good = A[A[:, 2] >= max(0.5, A[:, 2].max() * 0.9)]
    if len(good) == 0:
        fit.note = "locked only weakly; no window reached usable confidence"
        return fit

    tl, tg = good[:, 0], good[:, 1]
    offs = tg - tl

    # Lost-count steps: the offset jumps and stays jumped. A clock-rate error
    # instead moves it smoothly, which the slope below absorbs.
    segments, drops = [], []
    if len(good) >= 2:
        jumps = np.flatnonzero(np.abs(np.diff(offs)) > STEP_THRESHOLD_S)
        bounds = [0] + [int(j) + 1 for j in jumps] + [len(good)]
        for a, b in zip(bounds[:-1], bounds[1:]):
            if b - a < 1:
                continue
            if b - a >= 2:
                rate = float(np.polyfit(tl[a:b], tg[a:b], 1)[0])
            else:
                rate = 1.0
            offset = float(np.median(tg[a:b] - rate * tl[a:b]))
            t_end = tl[b - 1] if b < len(good) else float(src_edges[-1])
            segments.append((float(tl[a]), float(t_end), offset, rate))
        for k, j in enumerate(jumps):
            if k + 1 < len(segments):
                drops.append((float(tl[j + 1]),
                              float((segments[k+1][2] - segments[k][2]) * 1000)))

    if not segments:
        segments = [(float(src_edges[0]), float(src_edges[-1]),
                     float(np.median(offs)), 1.0)]

    fit.segments = segments if len(segments) > 1 else []
    fit.offset_s = segments[0][2]
    fit.rate = segments[0][3]
    fit.drift_ppm = (fit.rate - 1.0) * 1e6
    fit.drops = drops

    # Final pairing against the fitted map, for match rate and residuals.
    pred = fit.to_global(src_edges) if fit.segments else \
        fit.offset_s + fit.rate * src_edges
    ps, pt = _pair_at(src_edges, pred, sub["edges"], tol_s)
    fit.n_matched = int(len(ps))
    fit.match_rate = len(ps) / max(1, src_edges.size)
    if len(ps):
        resid = pt - (fit.to_global(ps) if fit.segments
                      else fit.offset_s + fit.rate * ps)
        fit.rms_ms = float(np.sqrt(np.mean(resid ** 2)) * 1000)
        fit.residual_ms = float(np.max(np.abs(resid)) * 1000)

    fit.ok = True
    return fit


# ---------------------------------------------------------------------------
# Stitching
# ---------------------------------------------------------------------------

def _resample_to(src_t, src_v, dst_t, how="linear", gap_s=None):
    """Put one channel on the common time base.

    Never interpolates across a gap: where the source has no samples within
    `gap_s`, the output is NaN. Inventing values across a dropped chunk would
    silently manufacture data.
    """
    src_t = np.asarray(src_t, float)
    src_v = np.asarray(src_v, float)
    good = np.isfinite(src_t) & np.isfinite(src_v)
    if good.sum() < 2:
        return np.full(dst_t.shape, np.nan)
    st, sv = src_t[good], src_v[good]

    if how == "nearest":
        idx = np.clip(np.searchsorted(st, dst_t), 1, len(st) - 1)
        left = st[idx - 1]
        right = st[idx]
        pick = np.where(np.abs(dst_t - left) <= np.abs(right - dst_t),
                        idx - 1, idx)
        out = sv[pick]
    else:
        out = np.interp(dst_t, st, sv, left=np.nan, right=np.nan)

    # Blank anything outside the source's coverage or inside a real gap.
    out[(dst_t < st[0]) | (dst_t > st[-1])] = np.nan
    if gap_s is not None and len(st) > 1:
        gaps = np.diff(st)
        for i in np.flatnonzero(gaps > gap_s):
            out[(dst_t > st[i]) & (dst_t < st[i + 1])] = np.nan
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def align_recordings(sources: Sequence[Source],
                     mode: str = "global_time",
                     resample: str = "linear",
                     target_fs: Optional[float] = None,
                     duration_s: Optional[float] = None,
                     run_id: Optional[int] = None,
                     tol_s: float = INTERVAL_TOL_S,
                     gap_factor: float = 3.0) -> AlignResult:
    """
    Align any number of recordings onto one timeline.

    Each source is locked independently to the code-generated template, so
    the result is transitive: sources need not overlap each other, share a
    sample rate, or report the sync signal the same way. A source may supply
    a continuous waveform, rising-edge timestamps only, falling-edge
    timestamps only, or both.

    Parameters
    ----------
    sources : list of Source
    mode :
        'lags'        — fits only; no data is touched.
        'global_time' — each source keeps its own samples and rate and gains
                        a global_time array. Nothing is resampled.
        'stitch'      — one merged table on a common time base.
    resample : stitch only. 'linear' (default) or 'nearest' — use 'nearest'
        for marker/categorical channels that must not be averaged.
    target_fs : stitch only. Common rate. Defaults to the FASTEST source
        rate, which upsamples the slower ones rather than discarding detail
        from the faster ones.
    duration_s : template length. Defaults to covering the latest edge seen.
    run_id : generator run to build the template for. Default None
        means read it from the recordings' own timecode frames,
        falling back to 1 when none decode.
    gap_factor : in stitch, a source gap wider than this many nominal sample
        periods is treated as missing data and filled with NaN rather than
        interpolated across.

    Returns
    -------
    AlignResult
    """
    if mode not in ("lags", "global_time", "stitch"):
        raise ValueError("mode must be 'lags', 'global_time', or 'stitch'")
    if not sources:
        raise ValueError("no sources given")

    span = max((s.edge_times[-1] if s.edge_times.size else 0.0)
               for s in sources)
    if duration_s is None:
        duration_s = max(60.0, span * 1.5 + 60.0)

    # Discover the run BEFORE building the template. Frame payloads encode
    # the run ID, so a template built for the wrong run has the right
    # pseudo-random train but different frame bits — offsets still come out
    # right (the frames supply them) while ~30% of edges fail to pair. Ask
    # the recordings which run they are, rather than assuming.
    if run_id is None:
        votes = []
        for s in sources:
            _, rid = decode_source_frames(s)
            if rid is not None:
                votes.append(rid)
        run_id = max(set(votes), key=votes.count) if votes else 1

    tmpl = build_template(duration_s, run_id=run_id)

    fits = [lock_source(s, tmpl, tol_s=tol_s) for s in sources]
    warnings = []

    # Run identity. A fixed seed makes every run's waveform identical, so the
    # decoded run ID is the only thing that distinguishes one start from
    # another. Recordings from different runs count elapsed time from
    # different zeros and CANNOT share a timeline — that is a hard error in
    # the making, not a warning to bury at the bottom.
    seen = {f.run_id for f in fits if f.run_id is not None}
    if len(seen) > 1:
        by_run = {}
        for f in fits:
            if f.run_id is not None:
                by_run.setdefault(f.run_id, []).append(f.name)
        detail = "; ".join(f"run {r}: {', '.join(n)}"
                           for r, n in sorted(by_run.items()))
        warnings.append(
            f"Recordings come from {len(seen)} DIFFERENT generator runs "
            f"({detail}). Each run restarts the elapsed clock from its own "
            f"zero, so these cannot be placed on one timeline. Split them by "
            f"run and align each group separately.")
    elif seen:
        only = next(iter(seen))
        for f in fits:
            if f.ok and f.run_id is None and f.source_of_lock == "fingerprint":
                warnings.append(
                    f"{f.name}: no timecode frame decoded, so it was located "
                    f"by pattern alone and its run could not be confirmed. It "
                    f"is assumed to belong to run {only}.")

    for f in fits:
        if not f.ok:
            warnings.append(f"{f.name}: {f.note}")
            continue
        if f.confidence < 0.3:
            warnings.append(
                f"{f.name}: weak lock (confidence {f.confidence:.2f}). The "
                f"winning alignment was proposed by only a minority of "
                f"windows — check the result before relying on it.")
        if f.match_rate < 0.5:
            warnings.append(
                f"{f.name}: only {100*f.match_rate:.0f}% of its edges matched "
                f"the template. Expect missing or spurious edges.")
        if abs(f.drift_ppm) > 1000:
            warnings.append(
                f"{f.name}: clock differs from the generator by "
                f"{f.drift_ppm:+.0f} ppm ({f.drift_ppm*3.6:.0f} ms per hour).")
        for t_local, step_ms in f.drops:
            warnings.append(
                f"{f.name}: possible dropped frames at t={t_local:.2f} s "
                f"(timeline steps by {step_ms:+.1f} ms).")

    result = AlignResult(mode=mode, fits=fits, sources=list(sources),
                         warnings=warnings)

    if mode == "lags":
        return result

    # global_time for every source that locked
    for src, f in zip(sources, fits):
        if not f.ok:
            continue
        if src.data is None and src.time is None and src.fs is None:
            result.global_time[src.name] = f.to_global(src.edge_times)
        else:
            result.global_time[src.name] = f.to_global(src.sample_times())

    if mode == "global_time":
        return result

    # ---- stitch ----------------------------------------------------------
    usable = [(s, f) for s, f in zip(sources, fits)
              if f.ok and s.data is not None]
    if not usable:
        raise ValueError("stitch needs at least one source with data that "
                         "locked to the template")

    if target_fs is None:
        rates = [s.fs for s, _ in usable if s.fs]
        target_fs = max(rates) if rates else 1000.0

    starts, ends = [], []
    for s, f in usable:
        g = result.global_time[s.name]
        starts.append(g[0])
        ends.append(g[-1])
    t0, t1 = min(starts), max(ends)
    common = np.arange(t0, t1, 1.0 / target_fs)

    columns = {}
    for s, f in usable:
        g = result.global_time[s.name]
        data = np.asarray(s.data)
        if data.ndim == 1:
            data = data[:, None]
        labels = s.labels or [f"ch{i}" for i in range(data.shape[1])]
        gap_s = (gap_factor / s.fs) if s.fs else None
        for c in range(data.shape[1]):
            columns[f"{s.name}.{labels[c]}"] = _resample_to(
                g, data[:, c], common, how=resample, gap_s=gap_s)

    result.table = {"time": common, "columns": columns,
                    "fs": target_fs, "n": len(common)}
    return result

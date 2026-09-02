#!/usr/bin/env python3
"""
truth.py - Score any recording against the waveform the generator actually
emitted, and produce corrected timestamps with a stated confidence.

THE PRINCIPLE

The PRE-Sync signal is deterministic, so the waveform that was on the wire can
be regenerated exactly. That makes it ground truth: a recording is judged
against what was emitted, not against another recording. This matters because
comparing two recordings to each other cannot say which of them is at fault —
and on real data, both were.

WHAT IT MEASURES, SEPARATELY

A recording can be wrong in four ways at once, and they need different fixes:

  OFFSET   a constant lag. Correctable exactly.
  DRIFT    the recorder's clock running fast or slow. Correctable, but only
           if measured; a constant offset will not hold across a long trial.
  JITTER   what is left once offset and drift are removed. Irreducible. This
           is the recorder's real timing precision and it sets the floor on
           any analysis.
  LOSS     transitions that never made it into the file at all. Not a timing
           error and not correctable — the data is gone. Reported separately
           so it is never confused with poor timing.

Reporting a single "error" number conflates all four and hides which one is
the problem.

WHAT MAKES THE LOCK ROBUST

Finding where a recording sits in a free-running generator's output is the
hard part, and the obvious approaches fail on real data:

  * The generator is usually ALREADY RUNNING when recording starts. Assuming
    the recording begins at template t=0 reports "no seed matches" on a
    perfectly good file. Two real recordings from one continuous run were
    located at 17.9 min and 41.1 min into it.

  * A fixed millisecond tolerance cannot survive drift or loss. At 300 ppm
    the accumulated position slides past any threshold, and a dropped event
    makes one interval the sum of two. Matching therefore compares interval
    RATIOS, so drift scales out.

  * Counting how many windows agree is the wrong score. A recording with a
    damaged opening locks weakly by that measure while being perfectly
    alignable. Candidates are scored by ANCHORED COVERAGE instead: anchor
    there, and count how many of the recording's events land on a real
    transition. On a wireless stream that scored "NO LOCK" under window
    voting, coverage scoring placed 100% of its events correctly.

Usage:
    from truth import score, correct

    r = score(edge_times)                    # both edges recorded
    r = score(trigger_times, both_edges=False)   # rises only
    print(r)

    t_true, conf = correct(edge_times, r)    # corrected timestamps

Dependencies: numpy, and timecode.py for template generation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

import timecode as tc

# Generator configuration. Fixed for this lab; override per call if it changes.
SEED = 42
MIN_HIGH_MS = 50
MAX_HIGH_MS = 500
MIN_LOW_MS = 50
MAX_LOW_MS = 500

# How far into a free-running session to search. A box left running all
# morning is deep into its sequence by the afternoon.
SEARCH_HOURS = 6.0

# Interval-ratio tolerance for the initial pattern match. Fractional rather
# than absolute so clock drift scales out instead of accumulating past a
# fixed threshold.
RATIO_TOL = 0.02

# Consecutive intervals per candidate window. Long enough to be unique in a
# pseudo-random sequence, short enough to be unlikely to span a dropped event.
CHUNK = 8

# A recorded transition within this of a true one is that transition. Wide
# enough for a recorder with poor timestamps, far below the 50 ms minimum
# pulse so it cannot pair with the wrong transition.
MATCH_WINDOW_S = 0.030


@dataclass
class TruthReport:
    """How one recording compares to what the generator emitted."""
    locked: bool = False
    note: str = ""

    start_s: float = float("nan")      # where in the run the recording begins
    coverage: float = float("nan")     # fraction of the recording's own events
                                       # that land on a real transition

    n_emitted: int = 0                 # transitions the generator produced
    n_recorded: int = 0                # transitions in the file
    n_captured: int = 0                # emitted ones the file actually has
    n_spurious: int = 0                # recorded ones that match nothing
    capture_pct: float = float("nan")
    lost_at_s: list = field(default_factory=list)

    offset_ms: float = float("nan")
    drift_ppm: float = float("nan")
    jitter_sd_ms: float = float("nan")
    jitter_p95_ms: float = float("nan")
    jitter_max_ms: float = float("nan")
    raw_sd_ms: float = float("nan")    # before correcting offset and drift

    span_s: float = float("nan")
    _fit: tuple = (0.0, 0.0)           # (drift slope, offset) in truth time
    _t0: float = 0.0                   # truth-time origin the fit is about
    _lock_off: float = 0.0             # recording clock - truth clock

    def __str__(self):
        if not self.locked:
            return f"NOT LOCATED — {self.note}"
        L = [f"  located {self.start_s/60:.1f} min into the generator's run  "
             f"({self.coverage*100:.0f}% of recorded events are real transitions)",
             f"  span {self.span_s:.1f} s",
             "",
             f"  CAPTURE   {self.n_captured} of {self.n_emitted} emitted "
             f"({self.capture_pct:.1f}%)"
             + (f"   — {self.n_emitted-self.n_captured} LOST"
                if self.n_captured < self.n_emitted else "   — none lost"),
             ]
        if self.n_spurious:
            L.append(f"            {self.n_spurious} recorded event(s) match no "
                     f"emitted transition")
        L += ["",
              f"  OFFSET    {self.offset_ms:+.2f} ms      (constant; correctable)",
              f"  DRIFT     {self.drift_ppm:+.1f} ppm = {self.drift_ppm*60/1000:+.2f} ms/min"
              f"   (correctable)",
              f"  JITTER    sd {self.jitter_sd_ms:.2f} ms, p95 "
              f"{self.jitter_p95_ms:.2f}, max {self.jitter_max_ms:.2f}"
              f"   (irreducible — this is the precision floor)",
              f"            uncorrected residual was sd {self.raw_sd_ms:.2f} ms",
              "",
              f"  VERDICT   {self.verdict}"]
        return "\n".join(L)

    @property
    def verdict(self) -> str:
        if not self.locked:
            return "could not be located in the generator's output"
        lost = 100 - self.capture_pct
        if lost > 10 and self.jitter_sd_ms > 5:
            return (f"DEGRADED — {lost:.0f}% of transitions lost and "
                    f"{self.jitter_sd_ms:.1f} ms jitter")
        if lost > 10:
            return (f"LOSSY BUT WELL TIMED — {lost:.0f}% lost, though what "
                    f"arrived is good to {self.jitter_sd_ms:.2f} ms")
        if self.jitter_sd_ms > 5:
            return (f"COMPLETE BUT IMPRECISE — nothing lost, but "
                    f"{self.jitter_sd_ms:.1f} ms jitter")
        return (f"GOOD — {self.capture_pct:.0f}% captured, "
                f"{self.jitter_sd_ms:.2f} ms jitter after correction")


def _template(both_edges=True, seed=SEED, hours=SEARCH_HOURS):
    times, levels = tc.generate_template(
        seed=seed, duration_s=hours * 3600,
        min_high=MIN_HIGH_MS, max_high=MAX_HIGH_MS,
        min_low=MIN_LOW_MS, max_low=MAX_LOW_MS,
        tc_enabled=False, run_id=1)
    T = np.asarray(times, float) / 1000.0
    if not both_edges:
        # A trigger line records one polarity only.
        T = T[np.asarray(levels, int) == 1]
    return T


def _locate(e, T, chunk=CHUNK, ratio_tol=RATIO_TOL, match_s=MATCH_WINDOW_S):
    """Where in T does the recording e sit? Returns (offset, coverage).

    Candidates come from interval-ratio matching, and are scored by how many
    of the recording's events land on a real transition once anchored there —
    not by how many windows agree, which under-rates a recording whose
    opening is damaged.
    """
    iv = np.diff(e)
    TI = np.diff(T)
    if len(iv) < chunk or len(TI) < chunk:
        return None
    W = np.lib.stride_tricks.sliding_window_view(TI, chunk)

    best = None
    for r0 in range(len(iv) - chunk + 1):
        p = iv[r0:r0 + chunk]
        rel = np.max(np.abs(W - p) / np.maximum(p, 1e-3), axis=1)
        for j in np.flatnonzero(rel < ratio_tol):
            off = e[r0] - T[j]
            pred = e - off
            k = np.clip(np.searchsorted(T, pred), 1, len(T) - 1)
            d = np.minimum(np.abs(T[k] - pred), np.abs(T[k - 1] - pred))
            hit = int((d < match_s).sum())
            if best is None or hit > best[0]:
                best = (hit, off)
    if best is None:
        return None
    return best[1], best[0] / len(e)


def score(edge_times, both_edges=True, seed=SEED, hours=SEARCH_HOURS,
          match_s=MATCH_WINDOW_S, upto_s=None) -> TruthReport:
    """Judge one recording against the emitted waveform.

    both_edges: False for a trigger line that logs only rising transitions.
    upto_s:     analyse only the first N seconds — useful for characterising
                timing on a clean stretch before any loss begins, since a
                dropout inflates every statistic computed across it.
    """
    r = TruthReport()
    e = np.sort(np.asarray(edge_times, float).ravel())
    if len(e) < CHUNK + 2:
        r.note = f"only {len(e)} transitions; need at least {CHUNK+2}"
        return r

    T = _template(both_edges, seed, hours)
    loc = _locate(e, T, match_s=match_s)
    if loc is None:
        r.note = (f"no part of this recording matches {hours:g} h of the "
                  f"generator's output — either it is not this signal, or it "
                  f"is too corrupted for any window to match")
        return r
    off, cov = loc
    r.locked = True
    r.coverage = cov

    pred = e - off
    if upto_s is not None:
        pred = pred[pred <= pred[0] + upto_s]
    r.start_s = float(pred[0])
    r.span_s = float(pred[-1] - pred[0])

    truth = T[(T >= pred[0]) & (T <= pred[-1])]
    r.n_emitted = len(truth)
    r.n_recorded = len(pred)

    pairs, lost = [], []
    for tt in truth:
        k = int(np.argmin(np.abs(pred - tt)))
        if abs(pred[k] - tt) < match_s:
            pairs.append((tt, pred[k]))
        else:
            lost.append(float(tt - truth[0]))
    if len(pairs) < 3:
        r.locked = False
        r.note = "located, but too few transitions matched to characterise"
        return r

    P = np.array(pairs)
    tt, rec = P[:, 0], P[:, 1]
    r.n_captured = len(P)
    r.capture_pct = 100.0 * len(P) / max(r.n_emitted, 1)
    r.lost_at_s = lost
    r.n_spurious = max(0, r.n_recorded - len(P))

    err = rec - tt
    r.raw_sd_ms = float(err.std() * 1000)

    # Decompose: a straight line through the error IS the offset and drift.
    slope, intercept = np.polyfit(tt - tt[0], err, 1)
    jit = (err - (slope * (tt - tt[0]) + intercept)) * 1000
    r.offset_ms = float(intercept * 1000)
    r.drift_ppm = float(slope * 1e6)
    r.jitter_sd_ms = float(jit.std())
    r.jitter_p95_ms = float(np.percentile(np.abs(jit), 95))
    r.jitter_max_ms = float(np.abs(jit).max())
    # Store the correction in the RECORDING's own clock, so correct() can be
    # applied to raw timestamps without the caller having to subtract the
    # lock offset first. Folding `off` into the intercept was wrong: the
    # drift term is measured against truth-time t0, so applying it to a raw
    # timestamp evaluated the slope at the wrong origin and made timing
    # 11x worse than doing nothing.
    r._lock_off = float(off)
    r._fit = (float(slope), float(intercept))
    r._t0 = float(tt[0])
    return r


def correct(sample_times, rep: TruthReport):
    """Corrected timestamps, on the generator's timeline, plus a confidence.

    Removes the measured offset and drift. What remains is the jitter, which
    is why the confidence returned is the jitter — it is the honest bound on
    how well any timestamp can be placed, and it does not shrink because the
    offset was removed.

    Returns (corrected_times, confidence_ms).
    """
    if not rep.locked:
        raise ValueError("cannot correct with an unlocked recording")
    slope, intercept = rep._fit
    t = np.asarray(sample_times, float)
    # Recording clock -> truth clock, then remove the fitted drift and offset.
    # The drift slope was measured against truth time, so it must be evaluated
    # there too.
    on_truth = t - rep._lock_off
    return on_truth - (slope * (on_truth - rep._t0) + intercept), rep.jitter_sd_ms


def compare(reports: dict):
    """Put several streams from one session side by side.

    Each has been scored against the generator independently, so a difference
    between them is attributable to the stream rather than to whichever was
    chosen as the reference.
    """
    print(f"\n  {'stream':22} {'captured':>10} {'offset':>9} {'drift':>10} "
          f"{'jitter':>9}")
    for name, r in reports.items():
        if not r.locked:
            print(f"  {name:22} {'NOT LOCATED':>10}")
            continue
        print(f"  {name:22} {r.capture_pct:9.1f}% {r.offset_ms:+8.2f}m "
              f"{r.drift_ppm:+9.1f}p {r.jitter_sd_ms:8.2f}m")
    ok = {k: v for k, v in reports.items() if v.locked}
    if len(ok) >= 2:
        names = list(ok)
        base = ok[names[0]]
        print(f"\n  relative to {names[0]}:")
        for n in names[1:]:
            v = ok[n]
            print(f"    {n:20} offset {v.offset_ms-base.offset_ms:+7.2f} ms   "
                  f"drift {v.drift_ppm-base.drift_ppm:+7.1f} ppm   "
                  f"jitter {v.jitter_sd_ms:.2f} vs {base.jitter_sd_ms:.2f} ms")

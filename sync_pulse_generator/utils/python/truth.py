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

    # Timing measured on transitions FAR from any loss. A dropout does not
    # only remove its own transition: the ones on either side of a gap are
    # the most likely to be mistimed, and including them attributes the
    # dropout's damage to the recorder's timing. Separating the two is what
    # distinguishes "loses data but times the rest perfectly" from "times
    # everything poorly" — on real data one stream went 2.44 -> 0.46 ms when
    # its dropout-adjacent transitions were excluded, while another barely
    # moved (2.49 -> 2.58), which is the difference between an intermittent
    # interruption and a genuinely noisy link.
    clean_n: int = 0
    clean_jitter_sd_ms: float = float("nan")
    clean_jitter_max_ms: float = float("nan")
    clean_offset_ms: float = float("nan")
    clean_drift_ppm: float = float("nan")

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
              f"            uncorrected residual was sd {self.raw_sd_ms:.2f} ms"]
        if self.clean_n and np.isfinite(self.clean_jitter_sd_ms):
            worse = self.jitter_sd_ms / max(self.clean_jitter_sd_ms, 1e-9)
            L += [f"",
                  f"  AWAY FROM LOSSES ({self.clean_n} transitions clear of any gap)",
                  f"            offset {self.clean_offset_ms:+.2f} ms, drift "
                  f"{self.clean_drift_ppm:+.1f} ppm, jitter sd "
                  f"{self.clean_jitter_sd_ms:.2f} ms, max "
                  f"{self.clean_jitter_max_ms:.2f} ms",
                  f"            {'the dropouts account for most of the apparent jitter'
                                 if worse > 2 else
                                 'jitter is spread through the recording, not just at gaps'}"
                  f" ({self.jitter_sd_ms:.2f} -> {self.clean_jitter_sd_ms:.2f} ms)"]
        L += ["",
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


# One PRE-Sync duration quantum. The generator can only emit multiples of
# this, so it is the natural unit for timing error: a recorder inside +/-0.5
# units can never be assigned to the wrong tick, whatever the millisecond
# figure happens to be.
STEP_MS = 5.0

# A transition off by more than this many quanta is not jitter — it is a
# single corrupted timestamp, and averaging it into a standard deviation
# misrepresents the recorder. One sample 28 ms out took a stream's apparent
# jitter from 0.53 ms to 2.44 ms; the other 142 were fine.
GROSS_UNITS = 3.0

# Consecutive missing transitions that count as an outage rather than
# scattered misses. An outage is ONE event however long, and is not a timing
# property: a 7.7 s stall and steady low-grade loss are different faults
# needing different responses.
OUTAGE_RUN = 3
OUTAGE_GAP_S = 2.0


def classify(edge_times, both_edges=True, **kw):
    """Separate the four things that go wrong, so none can hide inside another.

    Returns a dict with, kept strictly apart:

      jitter      spread of the well-behaved transitions, in ms AND in
                  PRE-Sync quanta. This is the recorder's real precision.
      gross       individual transitions off by more than GROSS_UNITS. Counted
                  and listed, never averaged into jitter.
      outages     runs of consecutive missing transitions — the stream
                  stopped. Reported as events with start, end and duration.
      isolated    single missing transitions with intact neighbours.

    Why bother: a 7.7 s stall, four scattered bad timestamps, and genuine
    link noise all appear as "jitter" and "% lost" if lumped together, and
    the same recording then reports anywhere from 0.5 ms to 2.6 ms depending
    on how it was sliced. Separated, each number is stable and points at a
    different fix.
    """
    r = score(edge_times, both_edges=both_edges, **kw)
    if not r.locked:
        return {"locked": False, "note": r.note}

    T = _template(both_edges, kw.get("seed", SEED), kw.get("hours", SEARCH_HOURS))
    pred = np.asarray(edge_times, float) - r._lock_off
    pred.sort()
    tr = T[(T >= pred[0]) & (T <= pred[-1])]
    t0 = tr[0]

    matched, errs, lost = [], [], []
    for x in tr:
        j = int(np.argmin(np.abs(pred - x)))
        if abs(pred[j] - x) < MATCH_WINDOW_S:
            matched.append(x - t0)
            errs.append((pred[j] - x) * 1000)
        else:
            lost.append(x - t0)
    matched = np.asarray(matched); errs = np.asarray(errs)
    lost = np.asarray(lost)

    slope, icept = np.polyfit(matched, errs / 1000, 1)
    res = (errs / 1000 - (slope * matched + icept)) * 1000

    # Outages: runs of consecutive losses.
    outages, isolated = [], []
    if len(lost):
        grp = [[lost[0]]]
        for x in lost[1:]:
            if x - grp[-1][-1] <= OUTAGE_GAP_S:
                grp[-1].append(x)
            else:
                grp.append([x])
        for g in grp:
            if len(g) >= OUTAGE_RUN:
                outages.append({"start_s": float(g[0]), "end_s": float(g[-1]),
                                "duration_s": float(g[-1] - g[0]),
                                "n_missed": len(g)})
            else:
                isolated += [float(x) for x in g]

    gross_m = np.abs(res) > GROSS_UNITS * STEP_MS
    clean = res[~gross_m]

    return {
        "locked": True,
        "n_emitted": len(tr), "n_captured": len(matched),
        "offset_ms": float(icept * 1000),
        "drift_ppm": float(slope * 1e6),
        "jitter_sd_ms": float(clean.std()),
        "jitter_max_ms": float(np.abs(clean).max()) if len(clean) else float("nan"),
        "jitter_sd_units": float(clean.std() / STEP_MS),
        "jitter_max_units": float(np.abs(clean).max() / STEP_MS) if len(clean) else float("nan"),
        "within_half_unit_pct": float(100 * np.mean(np.abs(clean) < STEP_MS / 2)),
        "n_gross": int(gross_m.sum()),
        "gross_at_s": [float(t) for t in matched[gross_m]],
        "gross_ms": [float(v) for v in res[gross_m]],
        "outages": outages,
        "n_outage_missed": int(sum(o["n_missed"] for o in outages)),
        "outage_s": float(sum(o["duration_s"] for o in outages)),
        "n_isolated": len(isolated),
        "isolated_at_s": isolated,
    }


def report(c, name=""):
    """Print a classify() result."""
    if not c.get("locked"):
        print(f"{name}: NOT LOCATED — {c.get('note','')}"); return
    lost = c["n_emitted"] - c["n_captured"]
    print(f"\n{name}")
    print(f"  captured        {c['n_captured']}/{c['n_emitted']} "
          f"({100*c['n_captured']/c['n_emitted']:.1f}%)")
    print(f"  offset          {c['offset_ms']:+.2f} ms          (constant — correctable)")
    print(f"  drift           {c['drift_ppm']:+.0f} ppm "
          f"({c['drift_ppm']*60/1000:+.2f} ms/min)  (correctable)")
    print(f"  JITTER          sd {c['jitter_sd_ms']:.2f} ms = {c['jitter_sd_units']:.3f} quanta, "
          f"max {c['jitter_max_units']:.2f} quanta")
    print(f"                  {c['within_half_unit_pct']:.1f}% land within half a quantum "
          f"(= on the correct 5 ms tick)")
    if c["n_gross"]:
        print(f"  GROSS ERRORS    {c['n_gross']} transition(s) off by >{GROSS_UNITS:.0f} quanta: "
              + ", ".join(f"{t:.1f}s ({v:+.0f} ms)"
                          for t, v in zip(c['gross_at_s'], c['gross_ms']))[:90])
        print(f"                  excluded from jitter — these are corrupt timestamps, "
              f"not spread")
    if c["outages"]:
        print(f"  OUTAGES         {len(c['outages'])} event(s), "
              f"{c['outage_s']:.1f}s total, {c['n_outage_missed']} transitions:")
        for o in c["outages"]:
            print(f"                    {o['start_s']:.1f}-{o['end_s']:.1f}s "
                  f"({o['duration_s']:.1f}s, {o['n_missed']} missed)")
    if c["n_isolated"]:
        print(f"  ISOLATED MISSES {c['n_isolated']}")
    if not c["outages"] and not c["n_gross"] and c["n_isolated"] <= 2:
        print(f"  -> clean: timing good to {c['jitter_sd_units']:.2f} quanta, no structural loss")


_TEMPLATE_CACHE = {}


def _template(both_edges=True, seed=SEED, hours=SEARCH_HOURS):
    # Cached: the template depends only on (seed, duration, polarity) and is
    # identical for every stream in a session. Regenerating six hours of it
    # per stream cost 1.5 s each and dominated the runtime — eight streams
    # spent more time rebuilding the same array than analysing the data.
    key = (bool(both_edges), seed, hours)
    if key in _TEMPLATE_CACHE:
        return _TEMPLATE_CACHE[key]
    times, levels = tc.generate_template(
        seed=seed, duration_s=hours * 3600,
        min_high=MIN_HIGH_MS, max_high=MAX_HIGH_MS,
        min_low=MIN_LOW_MS, max_low=MAX_LOW_MS,
        tc_enabled=False, run_id=1)
    T = np.asarray(times, float) / 1000.0
    if not both_edges:
        # A trigger line records one polarity only.
        T = T[np.asarray(levels, int) == 1]
    _TEMPLATE_CACHE[key] = T
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

    # COARSE THEN FINE.
    #
    # Six hours of template is ~78,000 windows, and comparing every probe
    # window against all of them is 25 million comparisons per stream — 8.7 s
    # of Python loop, which made eight streams take over a minute.
    #
    # A single probe window is enough to find the neighbourhood: the sequence
    # is pseudo-random, so a matching 8-interval run is already almost unique.
    # So use ONE probe to narrow the template to a small region, then run the
    # full multi-probe vote only inside it. Three earlier attempts at this
    # (striding the probes, caching the template, deduplicating candidates)
    # each made it slower, because they trimmed the cheap part and left the
    # 25-million-comparison loop intact.
    def _score(off):
        pred = e - off
        k = np.clip(np.searchsorted(T, pred), 1, len(T) - 1)
        d = np.minimum(np.abs(T[k] - pred), np.abs(T[k - 1] - pred))
        return int((d < match_s).sum())

    probe0 = iv[:chunk]
    rel0 = np.max(np.abs(W - probe0) / np.maximum(probe0, 1e-3), axis=1)
    seeds = np.flatnonzero(rel0 < ratio_tol)
    if not len(seeds):
        # Opening window is damaged; fall back to scanning a few probes.
        for r0 in range(0, min(len(iv) - chunk + 1, 40)):
            p = iv[r0:r0 + chunk]
            rel = np.max(np.abs(W - p) / np.maximum(p, 1e-3), axis=1)
            hit = np.flatnonzero(rel < ratio_tol)
            if len(hit):
                seeds = hit - r0 + 0            # express as index of probe 0
                seeds = seeds[seeds >= 0]
                break
    if not len(seeds):
        return None

    best = None
    for j0 in seeds[:200]:
        off = e[0] - T[j0]
        hit = _score(off)
        if best is None or hit > best[0]:
            best = (hit, off)
    if best is None:
        return None

    # Refine: re-anchor on the edge nearest the middle of the recording, which
    # is less sensitive to a damaged start or end than the first edge is.
    mid = len(e) // 2
    pred = e - best[1]
    j = int(np.clip(np.searchsorted(T, pred[mid]), 1, len(T) - 1))
    for jj in (j - 1, j, j + 1):
        if 0 <= jj < len(T):
            off = e[mid] - T[jj]
            hit = _score(off)
            if hit > best[0]:
                best = (hit, off)
    return best[1], best[0] / len(e)


def score(edge_times, both_edges=True, seed=SEED, hours=SEARCH_HOURS,
          match_s=MATCH_WINDOW_S, upto_s=None, guard_s=1.0) -> TruthReport:
    """Judge one recording against the emitted waveform.

    both_edges: False for a trigger line that logs only rising transitions.
    upto_s:     analyse only the first N seconds — useful for characterising
                timing on a clean stretch before any loss begins, since a
                dropout inflates every statistic computed across it.
    guard_s:    transitions within this of a lost one are excluded from the
                "clean" statistics reported alongside the overall ones.
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

    # Re-measure using only transitions well clear of any loss.
    if lost:
        lost_t = np.asarray(lost) + truth[0]
        far = np.array([np.min(np.abs(lost_t - t)) > guard_s for t in tt])
    else:
        far = np.ones(len(tt), bool)
    if far.sum() >= 5:
        ct, cr = tt[far], rec[far]
        cs, ci = np.polyfit(ct - ct[0], cr - ct, 1)
        cj = ((cr - ct) - (cs * (ct - ct[0]) + ci)) * 1000
        r.clean_n = int(far.sum())
        r.clean_offset_ms = float(ci * 1000)
        r.clean_drift_ppm = float(cs * 1e6)
        r.clean_jitter_sd_ms = float(cj.std())
        r.clean_jitter_max_ms = float(np.abs(cj).max())
    else:
        r.clean_n = int(far.sum())
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

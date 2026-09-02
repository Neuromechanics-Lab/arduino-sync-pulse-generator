"""
locate - find where in the generator's sequence a recording sits.

The problem this stage exists to solve: the box is free-running. It was
switched on before the session and left alone, so a recording that starts at
09:41 begins somewhere deep in a sequence that started hours earlier. Nothing
in the data says where. Assuming t=0 lines up with the template's t=0 is the
single most damaging mistake available here, and it produces a confident,
completely wrong alignment.

Two ways to answer it, in order of preference:

  TIMECODE  a decoded frame states the position outright. No search, checksum
            verified, and it also identifies which RUN was recorded — which a
            fixed seed makes otherwise indistinguishable.

  FINGERPRINT  match the pattern of interval durations. The sequence never
               repeats, so a run of a dozen intervals is unique within hours.

The fingerprint compares interval RATIOS, not absolute milliseconds. A recorder
running 60 ppm fast stretches every interval by the same factor, which leaves
ratios untouched but breaks any fixed-millisecond tolerance the further into a
recording you look. Matching on ratios means the search does not have to know
the clock error before it can find the signal — which is fortunate, since
measuring that error is the whole point of the next stage.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from .signal import template_edges, decode_frames, STEP_MS, SEARCH_HOURS

RATIO_TOL = 0.02       # 2% per interval; comfortably above jitter, far below
                       # the gap between adjacent 5 ms sequence values
CHUNK = 8              # intervals per fingerprint probe
MATCH_WINDOW_S = 0.030 # how close a template edge must be to count as matched
MIN_COVERAGE = 0.55    # a lock must place this share of the recorded edges
MIN_MATCHED = 12       # ...and at least this many, however short the stream


@dataclass
class Location:
    """Where a recording sits in the generator's sequence."""
    found: bool
    offset_s: float = 0.0          # add to recording time -> template time
    method: str = "none"           # 'timecode' | 'fingerprint' | 'none'
    run_id: int | None = None
    n_matched: int = 0
    n_edges: int = 0
    confidence: float = 0.0        # fraction of recorded edges placed
    notes: list = field(default_factory=list)

    @property
    def coverage_pct(self):
        return 100.0 * self.confidence


def locate(edge_times, both_edges=True, seed=None, hours=SEARCH_HOURS,
           chunk=CHUNK, ratio_tol=RATIO_TOL, match_s=MATCH_WINDOW_S,
           try_timecode=True):
    """Locate a recorded edge list within the emitted sequence."""
    e = np.sort(np.asarray(edge_times, float).ravel())
    loc = Location(found=False, n_edges=e.size)
    if e.size < chunk + 2:
        loc.notes.append(f"only {e.size} edges; need at least {chunk + 2}")
        return loc

    if try_timecode:
        tc = _from_timecode(e)
        if tc is not None:
            return tc

    kw = {} if seed is None else {"seed": seed}
    T = template_edges(both_edges=both_edges, hours=hours, **kw)
    return _by_fingerprint(e, T, chunk, ratio_tol, match_s, loc)


def _from_timecode(e):
    """Try to read position directly out of an embedded frame."""
    for pol in ("rising", "falling"):
        try:
            frames = decode_frames(e, edge=pol)
        except Exception:
            continue
        good = [f for f in frames if f.get("checksum_ok")]
        if not good:
            continue
        f = good[0]
        loc = Location(found=True, method="timecode", n_edges=e.size,
                       run_id=f.get("run_id"), n_matched=len(good),
                       confidence=1.0)
        loc.offset_s = float(f["seconds"]) - float(f["t_start"])
        loc.notes.append(
            f"{len(good)} verified frame(s), run {f.get('run_id')}; "
            f"position known outright, no search needed")
        return loc
    return None


def _by_fingerprint(e, T, chunk, ratio_tol, match_s, loc):
    """Coarse-then-fine ratio search.

    Naively scoring every candidate offset against six hours of template is
    tens of millions of comparisons in Python. Instead a probe taken from the
    recording narrows the template to a handful of plausible regions, and full
    scoring runs only there.

    The probe cannot assume its own intervals are clean. A trigger line that
    dropped one transition turns two consecutive template intervals into a
    single longer one, and a probe spanning that hole matches nothing --
    which reads as "this is not the signal" when in fact only one edge is
    missing. So several probes are taken from across the recording and any
    that finds candidates is accepted; a hole has to corrupt every one of them
    before the search gives up.
    """
    de = np.diff(e)
    if de.size < chunk:
        loc.notes.append("too few intervals to fingerprint")
        return loc
    dT = np.diff(T)
    ratT = dT[1:] / dT[:-1]

    # Probes spread across the recording, middle first: the start is the most
    # likely place to find a partial pulse or a settling amplifier.
    n_probe = max(1, de.size - chunk + 1)
    starts = sorted(range(0, n_probe, max(1, chunk // 2)),
                    key=lambda k: abs(k - (de.size - chunk) / 2))

    # Every probe that finds candidates contributes them, and the winner is
    # chosen by how much of the recording it actually places. Accepting the
    # first probe that matched instead would let one lucky-looking anchor in a
    # degraded stream win over a correct one, and the resulting offset is
    # confidently wrong rather than obviously absent.
    cands = []
    for p0 in starts[:24]:
        pr = de[p0+1:p0+chunk] / de[p0:p0+chunk-1]
        m = ratT.size - pr.size + 1
        if m <= 0:
            continue
        win = np.lib.stride_tricks.sliding_window_view(ratT, pr.size)[:m]
        hit = np.flatnonzero(np.max(np.abs(win - pr), axis=1) < ratio_tol)
        for k in hit.tolist():
            cands.append((k, p0))
        if len(cands) > 400:
            break

    if not cands:
        loc.notes.append(
            "no fingerprint match from any probe window. Check seed/timing "
            "configuration, the search window (hours=), and whether "
            "both_edges matches how this device records")
        return loc

    best = None
    for k, p0 in cands:
        off = T[k + 1] - e[p0 + 1]
        n = _count_matched(e + off, T, match_s)
        if best is None or n > best[0]:
            best = (n, off)
    n_matched, off = best

    # A lock has to place a real share of the recording. A handful of edges
    # will coincidentally line up somewhere in six hours of a non-repeating
    # sequence, and reporting that as a position produces a confident, wholly
    # wrong alignment -- far worse than saying nothing. Below the floor the
    # honest answer is that this recording could not be placed.
    if n_matched < MIN_MATCHED or n_matched / e.size < MIN_COVERAGE:
        loc.notes.append(
            f"best candidate placed only {n_matched}/{e.size} edges "
            f"({100.0*n_matched/e.size:.1f}%), below the {100*MIN_COVERAGE:.0f}% "
            f"floor for a trustworthy lock. Not reporting a position: too few "
            f"edges survived for any offset to be distinguishable from "
            f"coincidence. Likely heavy data loss or spurious triggers")
        return loc

    loc.found = True
    loc.method = "fingerprint"
    loc.offset_s = float(off)
    loc.n_matched = int(n_matched)
    loc.confidence = n_matched / e.size
    loc.notes.append(
        f"matched {n_matched}/{e.size} edges ({loc.coverage_pct:.1f}%) at "
        f"+{off:.1f} s into the sequence ({off/60:.1f} min)")
    if loc.confidence < 0.5:
        loc.notes.append(
            "under half the edges placed: treat this offset as provisional")
    return loc


def _count_matched(shifted, T, match_s):
    """How many recorded edges land near a template edge."""
    if shifted.size == 0:
        return 0
    i = np.searchsorted(T, shifted)
    i = np.clip(i, 1, T.size - 1)
    d = np.minimum(np.abs(T[i] - shifted), np.abs(T[i-1] - shifted))
    return int(np.count_nonzero(d <= match_s))

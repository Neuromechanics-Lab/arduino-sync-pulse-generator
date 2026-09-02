"""
combine - put independently measured streams on one timeline.

Each stream has already been measured against the emitted signal on its own,
which is the important structural choice: streams are never compared to each
other. Comparing them pairwise makes the answer depend on which one you picked
as reference, and if that one is the faulty one every other stream inherits
its fault.

So each is scored against the generator, and this stage only reports the
consequences: which stream is soundest, what the pairwise disagreement works
out to, and where they went dark together (a shared outage sits upstream of
both, so it is not either recorder's fault).
"""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from .measure import Measurement
from .signal import STEP_MS


@dataclass
class Combined:
    measurements: list = field(default_factory=list)
    reference: str = ""
    pairs: list = field(default_factory=list)     # (a, b, offset_ms, drift_ppm)
    shared_outages: list = field(default_factory=list)
    notes: list = field(default_factory=list)


def combine(measurements):
    c = Combined(measurements=list(measurements))
    ok = [m for m in c.measurements if m.location and m.location.found]
    if not ok:
        c.notes.append("no stream could be located; nothing to combine")
        return c

    # Rank on soundness first, precision second. Ranking on jitter alone once
    # elected a stream that had lost seven seconds of data but was beautifully
    # precise about the rest.
    c.reference = min(ok, key=lambda m: (
        len(m.outages), m.n_gross,
        -m.within_half_quantum_pct, -m.capture_pct, m.jitter_ms)).name
    c.notes.append(
        f"reference: '{c.reference}' (fewest outages and gross events, then "
        f"best on-tick fraction)")

    for i, a in enumerate(ok):
        for b in ok[i+1:]:
            c.pairs.append((a.name, b.name,
                            a.offset_ms - b.offset_ms,
                            a.drift_ppm - b.drift_ppm))

    c.shared_outages = _shared(ok)
    if c.shared_outages:
        c.notes.append(
            f"{len(c.shared_outages)} outage(s) present in every located "
            f"stream: the loss is upstream of the recorders, not in any one "
            f"of them")
    return c


def _shared(ms):
    """Outage windows that overlap across all located streams."""
    if not ms or any(not m.outages for m in ms):
        return []
    cur = [(a, b) for a, b, _ in ms[0].outages]
    for m in ms[1:]:
        nxt = []
        for a, b in cur:
            for x, y, _ in m.outages:
                lo, hi = max(a, x), min(b, y)
                if hi > lo:
                    nxt.append((lo, hi))
        cur = nxt
        if not cur:
            return []
    return cur

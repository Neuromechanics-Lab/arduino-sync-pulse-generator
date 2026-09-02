"""
measure - what a recorder did to the signal.

Once a recording is located, every recorded edge has a known true time, and
the difference between the two is the recorder's error. That error is not one
number. It separates into four things with different causes and different
remedies, and conflating them is how a stream gets called "bad" when it is
merely offset, or "fine" when it is quietly drifting:

  OFFSET   a constant lead or lag. Harmless. Subtract it and it is gone.

  DRIFT    the recorder's clock runs fast or slow, in ppm. Accumulates
           linearly, so it is invisible in a short recording and dominant in a
           long one. This is the one that hides: streaming layers reconcile
           offset between machines and do not touch rate, so a stream can look
           synchronised at the start and be tens of milliseconds out by the
           end.

  JITTER   the irreducible scatter left after removing offset and drift.
           A floor, not a fault; nothing downstream can correct it.

  LOSS     edges that are simply absent. Not a timing error at all — no
           amount of timestamp correction recovers a sample that was never
           recorded — so it is counted separately and never folded into
           jitter.

Errors are also reported in QUANTA: error divided by the generator's 5 ms
step. The generator cannot emit anything finer, so an error under half a
quantum is guaranteed to sit on the correct tick, and a percentage of edges
within half a quantum answers "can I trust this stream" more usefully than a
millisecond figure whose significance depends on the signal.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from .signal import template_edges, STEP_MS, SEARCH_HOURS
from .locate import Location, locate as _locate, MATCH_WINDOW_S

GROSS_UNITS = 3.0   # error beyond 3 quanta is a fault, not scatter
OUTAGE_RUN = 3      # consecutive misses before calling it an outage
OUTAGE_GAP_S = 2.0  # ...or a silence this long


@dataclass
class Measurement:
    """Per-stream timing performance against the emitted signal."""
    name: str = ""
    location: Location | None = None
    n_expected: int = 0
    n_captured: int = 0
    residual_ms: np.ndarray = field(default_factory=lambda: np.empty(0))
    matched_times: np.ndarray = field(default_factory=lambda: np.empty(0))
    offset_ms: float = 0.0
    drift_ppm: float = 0.0
    jitter_ms: float = 0.0
    within_half_quantum_pct: float = 0.0
    n_gross: int = 0
    gross_times: list = field(default_factory=list)
    outages: list = field(default_factory=list)   # (start_s, end_s, n_missed)
    duration_s: float = 0.0
    notes: list = field(default_factory=list)

    @property
    def capture_pct(self):
        return 100.0 * self.n_captured / self.n_expected if self.n_expected else 0.0

    @property
    def quanta(self):
        """Jitter expressed in generator steps."""
        return self.jitter_ms / STEP_MS

    @property
    def lost_s(self):
        return sum(b - a for a, b, _ in self.outages)

    @property
    def verdict(self):
        if self.outages:
            return "data loss"
        if abs(self.drift_ppm) > 100:
            return "drift"
        if self.quanta > 0.5:
            return "jitter above tick resolution"
        return "sound"


def measure(edge_times, both_edges=True, name="", location=None,
            seed=None, hours=SEARCH_HOURS, match_s=MATCH_WINDOW_S,
            gross_units=GROSS_UNITS):
    """Measure one stream against the emitted waveform."""
    e = np.sort(np.asarray(edge_times, float).ravel())
    m = Measurement(name=name)
    if e.size:
        m.duration_s = float(e[-1] - e[0])

    loc = location if location is not None else _locate(
        e, both_edges=both_edges, seed=seed, hours=hours, match_s=match_s)
    m.location = loc
    if not loc.found:
        m.notes.append("not located; nothing can be measured against truth")
        m.notes.extend(loc.notes)
        return m

    kw = {} if seed is None else {"seed": seed}
    T = template_edges(both_edges=both_edges, hours=hours, **kw)
    shifted = e + loc.offset_s

    # Expected edges are those the template emitted while this stream was
    # recording. Counting against the whole six-hour template would report
    # every stream as 99% lost.
    lo, hi = shifted[0] - match_s, shifted[-1] + match_s
    exp = T[(T >= lo) & (T <= hi)]
    m.n_expected = exp.size

    # Match each recorded edge to its nearest template edge.
    i = np.clip(np.searchsorted(T, shifted), 1, max(T.size - 1, 1))
    pick = np.where(np.abs(T[i] - shifted) < np.abs(T[i-1] - shifted), i, i-1)
    resid = (shifted - T[pick]) * 1000.0
    ok = np.abs(resid) <= match_s * 1000.0

    m.n_captured = int(ok.sum())
    m.residual_ms = resid[ok]
    m.matched_times = shifted[ok]
    if m.n_captured < 2:
        m.notes.append("fewer than two matched edges; no fit possible")
        return m

    _fit(m, gross_units)
    _find_outages(m, exp, T[pick][ok])
    return m


def _fit(m, gross_units):
    """Separate offset, drift and jitter out of the residuals.

    A straight line through residual-versus-time gives drift as its slope and
    offset as its value at the MIDDLE of the recording. Reporting the
    intercept at t=0 instead is a real trap: for a stream that starts hours
    into the sequence, t=0 is far outside the data and the extrapolated
    intercept is meaningless.
    """
    t, r = m.matched_times, m.residual_ms
    t0 = t.mean()
    slope, inter = np.polyfit(t - t0, r, 1)

    m.drift_ppm = float(slope * 1000.0)     # ms per s -> parts per million
    m.offset_ms = float(inter)
    detrended = r - (slope * (t - t0) + inter)
    m.jitter_ms = float(np.std(detrended))

    lim = gross_units * STEP_MS
    gross = np.abs(detrended) > lim
    m.n_gross = int(gross.sum())
    m.gross_times = [(float(a), float(b))
                     for a, b in zip(t[gross], detrended[gross])]
    if m.n_gross:
        # Recompute the floor without the gross events, so one corrupt
        # timestamp does not inflate the jitter figure for the whole stream.
        keep = ~gross
        if keep.sum() > 2:
            s2, i2 = np.polyfit(t[keep] - t0, r[keep], 1)
            m.drift_ppm = float(s2 * 1000.0)
            m.offset_ms = float(i2)
            detrended = r - (s2 * (t - t0) + i2)
            m.jitter_ms = float(np.std(detrended[keep]))
        m.notes.append(
            f"{m.n_gross} edge(s) beyond {gross_units:g} quanta excluded from "
            f"the jitter estimate; listed separately")

    half = STEP_MS / 2.0
    m.within_half_quantum_pct = float(
        100.0 * np.count_nonzero(np.abs(detrended) <= half) / detrended.size)


def _find_outages(m, expected, matched_template_times):
    """Group missing edges into contiguous outages.

    Scattered single misses and a four-second silence are different failures.
    One is detection marginality; the other is data that is gone.
    """
    if expected.size == 0:
        return
    got = np.isin(expected, matched_template_times)
    miss = ~got
    m.notes.append(
        f"{int(miss.sum())} of {expected.size} emitted edges not recorded")

    runs, i = [], 0
    while i < miss.size:
        if miss[i]:
            j = i
            while j < miss.size and miss[j]:
                j += 1
            runs.append((i, j))
            i = j
        else:
            i += 1
    for a, b in runs:
        n = b - a
        span = float(expected[b-1] - expected[a])
        if n >= OUTAGE_RUN or span >= OUTAGE_GAP_S:
            m.outages.append((float(expected[a]), float(expected[b-1]), int(n)))


def correct(sample_times, m):
    """Apply the measured offset and drift to a stream's own timestamps.

    Returns corrected times and the residual uncertainty in ms — the jitter,
    which is what remains and cannot be removed.

    Deliberately a single global line rather than interpolation between
    anchors. Interpolating looks like it should be better and measurably is
    not: each anchor carries its own detection noise, and threading a curve
    through them injects that noise into the corrected timestamps instead of
    averaging it away.
    """
    t = np.asarray(sample_times, float)
    if m.location is None or not m.location.found:
        raise ValueError(f"stream '{m.name}' was never located; cannot correct")
    t0 = m.matched_times.mean() - m.location.offset_s
    corr = t + m.location.offset_s \
             - (m.offset_ms + m.drift_ppm / 1000.0 * (t - t0)) / 1000.0
    return corr, m.jitter_ms

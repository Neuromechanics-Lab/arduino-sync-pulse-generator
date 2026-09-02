"""
detect - reduce a recording to transition times.

The one representation every recorder can produce. An analog channel carrying
the waveform and a trigger line logging brief pulses look nothing alike, but
both reduce to a list of times, and everything downstream works on that list.

This is why edge-only devices can be aligned at all: correlation needs two
signals that resemble each other, and a trigger line has no waveform to
correlate. Transition times it does have.
"""

from __future__ import annotations
import numpy as np


def edges_from_waveform(signal, times=None, fs=None, both_edges=True,
                        hysteresis=(0.3, 0.7)):
    """Transition times from a recorded analog copy of the square wave.

    Schmitt trigger with hysteresis to find the state changes, then linear
    interpolation across the mid-level crossing for sub-sample precision —
    which is how a 1000 Hz recorder reaches 0.43 ms.

    times: per-sample timestamps. Pass these rather than fs whenever the
           recorder provides them, since real acquisition is rarely perfectly
           regular and assuming it is folds that irregularity into the result.
    """
    x = np.asarray(signal, float).ravel()
    if times is None:
        if fs is None:
            raise ValueError("give either times= or fs=")
        times = np.arange(x.size) / fs
    t = np.asarray(times, float).ravel()
    if t.size != x.size:
        raise ValueError(f"times has {t.size} entries, signal has {x.size}")

    lo, hi = float(x.min()), float(x.max())
    if hi <= lo:
        return np.empty(0), np.empty(0, int)
    rng = hi - lo
    thr_lo, thr_hi = lo + hysteresis[0]*rng, lo + hysteresis[1]*rng
    mid = (hi + lo) / 2

    up = np.flatnonzero((x[1:] > thr_hi) & (x[:-1] <= thr_hi)) + 1
    dn = np.flatnonzero((x[1:] < thr_lo) & (x[:-1] >= thr_lo)) + 1
    idx = np.sort(np.concatenate([up, dn])) if both_edges else np.sort(up)
    pol = np.array([1 if i in set(up.tolist()) else -1 for i in idx], int)

    out = np.empty(idx.size)
    for n, i in enumerate(idx):
        rising = pol[n] > 0
        j = i
        while j > 0 and ((x[j] > mid) if rising else (x[j] < mid)):
            j -= 1
        if j < x.size - 1 and x[j+1] != x[j]:
            f = np.clip((mid - x[j]) / (x[j+1] - x[j]), 0, 1)
            out[n] = t[j] + f * (t[j+1] - t[j])
        else:
            out[n] = t[j]
    return out, pol


def edges_from_events(event_times, polarity="rising"):
    """Transition times from a device that logged events, not a waveform.

    A trigger input latches a brief pulse per transition, so what you have is
    already a list of times. polarity says which transitions those events
    correspond to, which determines what the template is compared against.
    """
    t = np.sort(np.asarray(event_times, float).ravel())
    if polarity == "rising":
        return t, np.ones(t.size, int)
    if polarity == "falling":
        return t, -np.ones(t.size, int)
    if polarity == "both":
        return t, np.zeros(t.size, int)
    raise ValueError("polarity must be 'rising', 'falling' or 'both'")


def edges_from_trigger_channel(values, times, threshold=0.5):
    """Transition times from a binary trigger channel sampled as a waveform.

    Only the RISES are events: the channel pulses high briefly per transition
    and returns low, so its falls mark the end of a pulse rather than a
    transition of the sync signal.
    """
    v = np.asarray(values, float).ravel()
    t = np.asarray(times, float).ravel()
    idx = np.flatnonzero((v[1:] > threshold) & (v[:-1] <= threshold)) + 1
    return t[idx], np.ones(idx.size, int)

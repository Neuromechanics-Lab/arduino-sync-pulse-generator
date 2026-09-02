"""
io - get edge times out of recording files.

Each loader's only job is to produce (name, edge_times, kind) tuples. Nothing
downstream knows or cares what format the data arrived in, which is what lets
an edge-only trigger log and a 2 kHz analog channel be analysed side by side.
"""

from __future__ import annotations
import numpy as np
from .detect import (edges_from_waveform, edges_from_events,
                     edges_from_trigger_channel)

MARKER_TYPES = {"markers", "marker", "events", "event", "trigger", "triggers",
                "stim", "stimulus"}


def load_xdf(path, keep=None):
    """Streams from an XDF recording.

    Marker streams give event times directly. Continuous streams are threshold
    detected, using each sample's own timestamp rather than an assumed rate,
    since irregular arrival is exactly the thing being measured.

    Two details that are easy to get wrong and quietly ruin the result:

      CHANNEL CHOICE  a 65-channel EEG stream carries the sync signal on one
                      channel and brain activity on the rest. The sync channel
                      is the one that spends its time pinned at two levels,
                      not the one with the largest range -- an EEG artefact
                      can easily out-range a 5 V square wave after scaling.

      POLARITY        a trigger channel pulses briefly per transition, so only
                      its RISES are events. Taking both edges there halves
                      every interval and nothing will ever match.

    Also returns the clock_offsets the streaming layer recorded, which are
    worth reporting alongside the measured error: the layer reconciles offset
    between machines and does not touch rate, so agreement on offset with
    disagreement on drift is the expected picture, not a contradiction.
    """
    import pyxdf
    streams, header = pyxdf.load_xdf(path)
    out, offsets = [], {}
    for s in streams:
        info = s["info"]
        name = info["name"][0]
        if keep and name not in keep:
            continue
        ts = np.asarray(s["time_stamps"], float)
        if ts.size < 20:
            continue

        clk = None
        try:
            v = [float(x["value"][0]) for x in
                 s["footer"]["info"]["clock_offsets"][0]["offset"]]
            if v:
                offsets[name] = np.asarray(v)
                clk = float(np.median(v))
        except Exception:
            pass

        stype = (info["type"][0] if info.get("type") else "").lower()
        d = np.asarray(s["time_series"])

        if stype in MARKER_TYPES or d.dtype.kind not in "fiu" or d.ndim != 2:
            e, _ = edges_from_events(ts, "rising")
            if clk is not None:
                e = e + clk
            out.append((name, e, "events"))
            continue

        labels = []
        try:
            labels = [c["label"][0] for c in
                      info["desc"][0]["channels"][0]["channel"]]
        except Exception:
            pass

        best = None
        for ci in range(d.shape[1]):
            col = d[:, ci].astype(float)
            if not np.isfinite(col).all() or col.std() == 0:
                continue
            lab = labels[ci] if ci < len(labels) else f"ch{ci}"
            lo, hi = col.min(), col.max()
            mid = (lo + hi) / 2.0
            up = np.flatnonzero((col[1:] > mid) & (col[:-1] <= mid)) + 1
            if up.size < 5:
                continue
            is_trig = "trig" in lab.lower()
            if is_trig:
                e, _ = edges_from_trigger_channel(col, ts, threshold=mid)
            else:
                e, _ = edges_from_waveform(col, times=ts)
            frac_ext = float(np.mean((col < lo + 0.1*(hi-lo)) |
                                     (col > hi - 0.1*(hi-lo))))
            score = frac_ext + (1.0 if is_trig else 0.0)
            if best is None or score > best[0]:
                best = (score, lab, e, is_trig)

        if best is None:
            continue
        _, lab, e, is_trig = best
        if clk is not None:
            e = e + clk
        out.append((f"{name}::{lab}", e,
                    "events" if is_trig else "continuous"))
    return out, offsets


def load_csv(path, time_col=0, value_col=1, threshold=None):
    """A two-column CSV of time and value, or of event times alone."""
    d = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    if d.shape[1] == 1:
        e, _ = edges_from_events(d[:, 0], "rising")
        return e, "events"
    t, v = d[:, time_col], d[:, value_col]
    e, _ = edges_from_waveform(v, times=t)
    return e, "continuous"


def load_c3d(path, channel=None):
    """An analog channel from a C3D file."""
    import ezc3d
    c = ezc3d.c3d(path)
    labels = [s.strip() for s in c["parameters"]["ANALOG"]["LABELS"]["value"]]
    rate = float(c["parameters"]["ANALOG"]["RATE"]["value"][0])
    data = c["data"]["analogs"][0]
    if channel is None:
        idx = 0
    else:
        # Match the label after the last '.' first: a bare substring search
        # matches the 'ta' inside every 'Voltage.' prefix and returns
        # everything.
        tails = [l.rsplit(".", 1)[-1] for l in labels]
        hits = [i for i, t in enumerate(tails) if t == channel] \
            or [i for i, t in enumerate(tails) if channel.lower() in t.lower()] \
            or [i for i, l in enumerate(labels) if channel.lower() in l.lower()]
        if not hits:
            raise ValueError(f"no channel matching '{channel}' in {labels}")
        idx = hits[0]
    x = np.asarray(data[idx], float)
    e, _ = edges_from_waveform(x, times=np.arange(x.size) / rate)
    return e, "continuous"

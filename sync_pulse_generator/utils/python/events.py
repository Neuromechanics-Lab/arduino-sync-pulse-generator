"""
events.py - decode the PRE-Sync event channel.

One output is split off from the sync train and carries events instead. Every
trigger arriving on TRIG IN emits a marker there, and the marker's LEADING
EDGE is the event, at interrupt latency. Everything after it is an identifier
and does not affect the timing.

    [200 ms MARK][gap][8 symbols, MSB first][gap]

A symbol is 50 ms for 0 and 100 ms for 1, each followed by a 50 ms gap, so
the payload is an 8-bit per-run event counter. The whole marker is 1050-1450
ms depending on the value.

WHY THIS EXISTS SEPARATELY FROM THE TRAIN. A plain event flag tells you when
something happened on each recorder's own clock, and nothing else. It cannot
distinguish a recorder that is 3 ms late from one drifting through 3 ms, one
jittering by 3 ms, or one that dropped a sample -- and those need different
remedies. The train answers that, because it is non-repeating and therefore
measurable everywhere rather than only at the event. The event channel adds
the one thing the train cannot supply: which trigger this was.

WHY THE WIDTHS ARE WHAT THEY ARE. Sized for the slowest recorder that might
see it. At 24 fps a frame is 41.7 ms and a pulse must exceed one full frame
interval to be caught regardless of phase. The 200 ms mark spans 4.8 frames;
the two symbols span 1.2 and 2.4 and stay distinguishable.
"""

from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np

MARK_MS = 200
GAP_MS = 50
BIT0_MS = 50
BIT1_MS = 100
COUNTER_BITS = 8

# A symbol is classified by which nominal width it is closer to. The two are
# 50 ms apart, so the threshold sits 25 ms from each -- far outside any
# plausible recorder jitter, which is the point of choosing widths this far
# apart rather than packing more bits in.
_SYM_THRESH_MS = (BIT0_MS + BIT1_MS) / 2.0
_MARK_MIN_MS = (BIT1_MS + MARK_MS) / 2.0     # 150 ms: above any symbol


@dataclass
class Event:
    """One decoded trigger."""
    time_s: float                  # the mark's leading edge: the event itself
    number: int | None = None      # 8-bit per-run counter, None if undecoded
    mark_ms: float = 0.0
    complete: bool = False         # payload fully decoded and unambiguous
    note: str = ""

    def __repr__(self):
        n = f"#{self.number}" if self.number is not None else "#?"
        return (f"Event({n} at {self.time_s:.4f}s"
                f"{'' if self.complete else ', payload incomplete'})")


def decode_events(edge_times, levels=None, tol_ms=15.0):
    """Decode event markers from the event channel's transitions.

    edge_times: transition times in seconds.
    levels:     optional 1/-1 per edge (1 = rising). If omitted, edges are
                assumed to alternate starting with a rise, which holds for a
                channel that idles LOW.

    Returns a list of Event. A marker whose payload was cut short -- the
    firmware aborts it when a new trigger arrives -- still yields an Event
    with its timestamp and complete=False, because the timing is the part
    that matters and it is never sacrificed.
    """
    t = np.asarray(edge_times, float).ravel()
    if t.size == 0:
        return []
    order = np.argsort(t)
    t = t[order]
    if levels is None:
        lv = np.where(np.arange(t.size) % 2 == 0, 1, -1)
    else:
        lv = np.asarray(levels, int).ravel()[order]

    # Pulse widths: each rise paired with the next fall.
    pulses = []          # (start_s, width_ms)
    for i in range(t.size - 1):
        if lv[i] > 0 and lv[i + 1] < 0:
            pulses.append((t[i], (t[i + 1] - t[i]) * 1000.0))
    if not pulses:
        return []

    events, i = [], 0
    while i < len(pulses):
        start, w = pulses[i]
        if w < _MARK_MIN_MS:
            i += 1                      # not a mark; skip stray pulse
            continue

        ev = Event(time_s=float(start), mark_ms=float(w))
        bits, j = [], i + 1
        while j < len(pulses) and len(bits) < COUNTER_BITS:
            _, pw = pulses[j]
            if pw >= _MARK_MIN_MS:
                break                   # next marker began: payload aborted
            bits.append(1 if pw >= _SYM_THRESH_MS else 0)
            j += 1

        if len(bits) == COUNTER_BITS:
            n = 0
            for b in bits:
                n = (n << 1) | b
            ev.number = n
            ev.complete = True
        else:
            ev.note = (f"payload cut short after {len(bits)} of "
                       f"{COUNTER_BITS} bits; timestamp is still exact")
        events.append(ev)
        i = j

    return events


def event_report(events, name=""):
    """Readable summary of a decoded event channel."""
    L = [f"Event channel{(' — ' + name) if name else ''}",
         f"  {len(events)} event(s)"]
    if not events:
        L.append("  nothing decoded: check that this channel carries the "
                 "event output, not the sync train")
        return "\n".join(L)

    for e in events:
        n = f"{e.number:3d}" if e.number is not None else "  ?"
        L.append(f"    event {n}  t = {e.time_s:10.4f} s"
                 + (f"   [{e.note}]" if e.note else ""))

    nums = [e.number for e in events if e.number is not None]
    if len(nums) > 1:
        gaps = [b - a for a, b in zip(nums, nums[1:])]
        missing = [g - 1 for g in gaps if g > 1]
        if any(g != 1 for g in gaps):
            L.append(f"  WARNING: counter is not consecutive — "
                     f"{sum(missing)} event(s) apparently missed by this "
                     f"recorder")
    inc = [e for e in events if not e.complete]
    if inc:
        L.append(f"  {len(inc)} marker(s) had their payload cut short by a "
                 f"following trigger. Timestamps are unaffected.")
    return "\n".join(L)

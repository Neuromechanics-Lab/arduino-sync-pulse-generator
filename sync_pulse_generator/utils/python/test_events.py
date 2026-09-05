#!/usr/bin/env python3
"""
Self-tests for events.py. Run directly:  python3 test_events.py

The event channel's whole claim is that the mark's leading edge is the event
and the payload cannot compromise it. These tests pin that: a marker whose
payload is cut short must still yield an exact timestamp, and a payload must
never decode to a plausible-but-wrong number.
"""
import sys
import events

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name +
          ("" if cond else ("\n         " + detail if detail else "")))


def _marker(val, nbits=events.COUNTER_BITS):
    segs = [("H", events.MARK_MS)]
    for i in range(nbits):
        segs.append(("L", events.GAP_MS))
        bit = (val >> (events.COUNTER_BITS - 1 - i)) & 1
        segs.append(("H", events.BIT1_MS if bit else events.BIT0_MS))
    return segs


def _stream(markers, t0=5.0, spacing=3.0, jitter_ms=0.0):
    import random
    rng = random.Random(7)
    ts, lv, t = [], [], t0
    for segs in markers:
        for st, d in segs:
            j = rng.uniform(-jitter_ms, jitter_ms) / 1000.0 if jitter_ms else 0.0
            ts.append(t + j)
            lv.append(1 if st == "H" else -1)
            t += d / 1000.0
        ts.append(t); lv.append(-1)
        t += spacing
    return ts, lv


def test_decodes_the_counter():
    for val in (0, 1, 5, 127, 128, 255):
        ts, lv = _stream([_marker(val)])
        e = events.decode_events(ts, lv)
        ok = len(e) == 1 and e[0].number == val and e[0].complete
        check(f"decodes event number {val}", ok,
              f"got {[x.number for x in e]}")


def test_timestamp_is_the_mark_leading_edge():
    ts, lv = _stream([_marker(9)], t0=12.3456)
    e = events.decode_events(ts, lv)
    ok = e and abs(e[0].time_s - 12.3456) < 1e-9
    check("timestamp is the mark's leading edge", ok,
          f"got {e[0].time_s if e else None}, expected 12.3456")


def test_aborted_payload_keeps_its_timestamp():
    """The firmware cuts a marker short when a new trigger arrives.

    Event timing is never sacrificed to finish an identifier, so a truncated
    marker must still produce an exact timestamp -- flagged, not dropped, and
    never decoded to a wrong number from partial bits.
    """
    truncated = _marker(3)[:1 + 2 * 3]
    ts, lv = _stream([truncated, _marker(4)])
    e = events.decode_events(ts, lv)
    ok = (len(e) == 2
          and abs(e[0].time_s - 5.0) < 1e-9
          and e[0].number is None and not e[0].complete
          and e[1].number == 4)
    check("aborted payload keeps an exact timestamp", ok,
          f"got {e}")


def test_survives_recorder_jitter():
    """Symbols are 50 ms apart so the threshold sits 25 ms from each.

    That margin is the reason for choosing widths this far apart rather than
    packing more bits in, and it should absorb any plausible jitter.
    """
    ts, lv = _stream([_marker(170)], jitter_ms=8.0)
    e = events.decode_events(ts, lv)
    ok = len(e) == 1 and e[0].number == 170
    check("decodes correctly with 8 ms of edge jitter", ok,
          f"got {[x.number for x in e]}, expected [170]")


def test_ignores_a_channel_carrying_the_train():
    """Pointed at the sync train instead of the event channel, it must not
    invent events. Train pulses are 50-500 ms, so some exceed the mark
    threshold -- but a real marker is followed by a payload."""
    import truth
    T = truth._template(both_edges=True)
    seg = T[(T >= 100) & (T <= 130)]
    lv = [1 if i % 2 == 0 else -1 for i in range(len(seg))]
    e = events.decode_events(seg, lv)
    complete = [x for x in e if x.complete]
    check("does not decode complete events from the sync train",
          len(complete) == 0,
          f"invented {len(complete)} complete event(s) from train data")


def test_empty_input():
    check("empty input returns no events", events.decode_events([]) == [])


def main():
    for fn in [v for k, v in sorted(globals().items())
               if k.startswith("test_")]:
        fn()
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

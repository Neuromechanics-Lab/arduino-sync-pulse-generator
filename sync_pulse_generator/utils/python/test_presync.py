#!/usr/bin/env python3
"""
Self-tests for the presync package. Run directly:  python3 test_presync.py

The package is an ordering layer over verified analysis code, so these tests
guard two different things.

The synthetic tests pin behaviour that must hold for any recording: a stream
that starts hours into a free-running generator is still located, a stream
whose clock is offset by a large constant is still located, and a stream with
a hole reports the hole rather than silently mis-scoring around it.

The regression test pins the numbers themselves against four real streams
from a session where the answer is independently known. That test exists
because a rewrite once dropped the LSL clock offset at load time, which moved
a stream days away from the template; every downstream figure changed, and
nothing failed. Numbers that are known to be right must fail loudly when they
stop being right.
"""
import sys
import numpy as np

import presync
import truth
import timecode as tc

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name + (
        "" if cond else ("\n         " + detail if detail else "")))


def _edges(start_s, dur_s, rising_only=False):
    """Recorded edge times for a window of the generator's output.

    Sliced out of the same template the analysis builds, deliberately. An
    earlier version of this helper called generate_template() with its own
    shorter duration, which yields a DIFFERENT edge sequence -- the generator
    is a running PRNG, so asking for 1900 s of it is not the first 1900 s of
    6 h. Tests built that way fail against correct code.
    """
    T = truth._template(both_edges=not rising_only)
    return T[(T >= start_s) & (T <= start_s + dur_s)]


# ---------------------------------------------------------------------------
# synthetic: the invariants
# ---------------------------------------------------------------------------

def test_locates_deep_into_a_free_running_sequence():
    """The box is switched on long before recording starts.

    Assuming the recording begins at the template's t=0 is the single most
    damaging mistake available here: it produces a confident, wholly wrong
    alignment rather than an obvious failure.
    """
    start = 1800.0
    e = _edges(start, 60.0)
    c = presync.classify(e, both_edges=True)
    got = c.get("n_captured", 0)
    check("locates a recording starting 30 min into the run",
          got >= 0.95 * len(e), f"captured {got} of {len(e)} recorded edges")


def test_trigger_channel_edges_match_the_verified_loader():
    """Edge detection on a trigger channel must reproduce analyze.load_xdf.

    A rewrite once produced the same NUMBER of edges from this stream (86)
    with individual intervals differing by up to 307 ms -- a different set of
    transitions detected from the same channel. Nothing raised an error: the
    stream still located, just against the wrong pattern, and scored 30/104
    instead of 86/105.

    Counting edges is therefore not enough to know a loader is right. This
    pins the intervals, which is what the fingerprint search actually
    consumes.
    """
    import os
    if not os.path.exists(FILES[1][1]):
        print("  skip  reference recording not present on this machine")
        return
    import analyze as _an
    ant = next((s for s in _an.load_xdf(FILES[1][1])
                if "EE224" in s.name), None)
    if ant is None:
        check("trigger edges match verified loader", False, "stream not found")
        return
    iv = np.diff(ant.times) * 1000.0
    ok = (len(ant.times) == 86
          and abs(float(np.median(iv)) - 568.47) < 0.5
          and abs(float(iv.max()) - 4690.88) < 1.0)
    check("trigger channel edges match the verified loader", ok,
          f"n={len(ant.times)} median={np.median(iv):.2f} max={iv.max():.2f} "
          f"(expected 86 / 568.47 / 4690.88)")


def test_reports_a_hole_rather_than_scoring_around_it():
    """Missing data is loss, not a timing error, and must be named as such."""
    e = _edges(300.0, 120.0)
    keep = (e < 340.0) | (e > 350.0)          # punch out ~10 s
    c = presync.classify(e[keep], both_edges=True)
    outs = c.get("outages") or []
    check("a 10 s hole is reported as an outage", len(outs) >= 1,
          f"outages found: {len(outs)}")


def test_rising_only_stream_is_not_scored_against_both_edges():
    """A trigger line logs one polarity.

    Scored against a both-edges template every interval halves and nothing
    matches, so the polarity has to travel with the stream.
    """
    e = _edges(300.0, 90.0, rising_only=True)
    right = presync.classify(e, both_edges=False)
    check("rising-only stream locates with both_edges=False",
          right.get("n_captured", 0) >= 0.9 * len(e),
          f"captured {right.get('n_captured')} of {len(e)}")


def test_template_is_deterministic():
    """Same seed and configuration, same waveform -- this is what makes the
    emitted signal usable as ground truth at all."""
    a = _edges(0.0, 30.0)
    b = _edges(0.0, 30.0)
    check("template regeneration is bit-identical",
          len(a) == len(b) and np.array_equal(a, b))


# ---------------------------------------------------------------------------
# regression: the real numbers
# ---------------------------------------------------------------------------

B = ("/Users/nathanbaune/Research/contracting-docs/uvm-2026/mirdamadi-lab"
     "/DataLSLTest/sub-P001")

# Verified against the session these came from. n_captured/n_emitted and the
# on-tick percentage are the figures the analysis is reported on, so they are
# the ones pinned here.
EXPECTED = {
    "wired|KINARM_AnalogInputs::ch0":
        dict(n_captured=120, n_emitted=120, within_half_unit_pct=100.0),
    "wired|EE224-020034-000036_on_DESKTOP-AOD47FU::Trigger":
        dict(n_captured=59, n_emitted=61, within_half_unit_pct=98.3),
    "wireless|KINARM_AnalogInputs::ch0":
        dict(n_captured=143, n_emitted=170, within_half_unit_pct=100.0),
    "wireless|EE224-020034-000036_on_DESKTOP-AOD47FU::Trigger":
        dict(n_captured=86, n_emitted=105, within_half_unit_pct=82.6),
}

FILES = [
    ("wired", B + "/ses-S001antwired/eeg/"
              "sub-P001_ses-S001antwired_task-Default_run-002_eeg.xdf"),
    ("wireless", B + "/ses-S001antwireless/eeg/"
                 "sub-P001_ses-S001antwireless_task-Default_run-001_eeg_old1.xdf"),
]


def test_reference_session_reproduces():
    import os
    if not all(os.path.exists(f) for _, f in FILES):
        print("  skip  reference recordings not present on this machine")
        return
    # These recordings predate the timer-driven firmware and were emitted on
    # a 5 ms quantum. Nothing else about them differs -- same seed, same
    # pseudo-random square wave, no timecode -- so the step is the only thing
    # the analysis needs told, and step_ms= is the whole mechanism.
    import analyze as _an
    import truth as _t
    got = {}
    for tag, f in FILES:
        for s in _an.load_xdf(f):
            got[tag + "|" + s.name] = _t.classify(
                s.times, both_edges=s.both_edges, step_ms=5)

    for key, exp in EXPECTED.items():
        c = got.get(key)
        if c is None:
            check(f"reference stream present: {key.split('|')[0]} "
                  f"{key.split('::')[-1]}", False, "stream missing from result")
            continue
        bad = []
        for field, want in exp.items():
            have = c.get(field)
            if have is None or abs(float(have) - want) > 0.05:
                bad.append(f"{field}: expected {want}, got {have}")
        check(f"reference {key.split('|')[0]} {key.split('::')[-1][:24]} "
              f"reproduces", not bad, "; ".join(bad))


def main():
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Self-tests for align.py. Run directly:  python3 test_align.py

Each test is a case that broke an earlier implementation. Between them they
pin the behaviour that matters: mixed source types, different sample rates,
clock drift, missing data, and lost-count steps.
"""
import sys
import numpy as np
import align as al

TMPL = al.build_template(300, run_id=1)
T = TMPL["time"]
P = TMPL["polarity"]


def _jit(x, rng, sd=0.0008):
    return np.asarray(x, float) + rng.normal(0, sd, len(x))


def _continuous(name, start, fs, dur, rng, rate=1.0, payload=True):
    n = int(dur * fs)
    tt = np.arange(n) / fs
    g = start + tt * rate
    sync = (np.searchsorted(T, g, side="right") % 2).astype(float)
    sync = sync + rng.normal(0, 0.01, n)
    data = np.column_stack([sync, np.sin(2 * np.pi * 3 * tt)]) if payload else sync[:, None]
    labels = ["sync", "signal"] if payload else ["sync"]
    return al.Source.from_continuous(name, sync, fs=fs, data=data, labels=labels)


def test_offset_only():
    rng = np.random.default_rng(1)
    base = T[(T > 5) & (T < 180)] - 5.0
    f = al.lock_source(al.Source.from_edges("x", _jit(base, rng)), TMPL)
    assert f.ok, f.note
    assert abs(f.offset_s - 5.0) < 0.01, f.offset_s
    assert f.match_rate > 0.98, f.match_rate
    assert not f.drops, f.drops
    print("ok   pure offset recovered, no phantom drops")


def test_edge_only_rising_and_falling():
    """The headline case: a device that reports only one edge polarity."""
    rng = np.random.default_rng(2)
    w = (T > 20) & (T < 140)
    for pol, sel in (("rising", P > 0), ("falling", P < 0)):
        e = _jit(T[w & sel] - 20.0, rng)
        f = al.lock_source(al.Source.from_edges("x", e, polarity=pol), TMPL)
        assert f.ok, f"{pol}: {f.note}"
        assert abs(f.offset_s - 20.0) < 0.01, f"{pol}: {f.offset_s}"
        assert f.match_rate > 0.98, f"{pol}: {f.match_rate}"
    print("ok   rising-only and falling-only both lock")


def test_clock_drift():
    """A 300 ppm error moves alignment ~57 ms over 3 min — far outside any
    fixed pairing window, which is what broke the first implementation."""
    rng = np.random.default_rng(3)
    e = T[(T > 10) & (T < 200)]
    local = _jit((e - 10.0) / 1.0003, rng)
    f = al.lock_source(al.Source.from_edges("x", local), TMPL)
    assert f.ok, f.note
    assert abs(f.offset_s - 10.0) < 0.02, f.offset_s
    assert 250 < f.drift_ppm < 350, f.drift_ppm
    assert f.match_rate > 0.95, f.match_rate
    print("ok   300 ppm clock drift recovered")


def test_missing_block_is_not_a_drop():
    """Honest timestamps with a chunk of samples missing leave a HOLE, not a
    shift. Reporting drops here was a long-standing false positive."""
    rng = np.random.default_rng(4)
    base = T[(T > 5) & (T < 180)] - 5.0
    tt = base[(base < 55.0) | (base > 55.25)]
    f = al.lock_source(al.Source.from_edges("x", _jit(tt, rng)), TMPL)
    assert f.ok, f.note
    assert abs(f.offset_s - 5.0) < 0.01, f.offset_s
    assert not f.drops, f"phantom drops: {f.drops}"
    assert f.match_rate > 0.98, f.match_rate
    print("ok   missing block leaves a hole, reported as no drop")


def test_lost_count_step():
    """A counter-based recorder that loses 250 ms labels everything after it
    early. That IS a step and must be split into segments."""
    rng = np.random.default_rng(5)
    base = T[(T > 5) & (T < 180)] - 5.0
    tt = base[(base < 55.0) | (base > 55.25)]
    local = _jit(np.where(tt > 55.0, tt - 0.25, tt), rng)
    f = al.lock_source(al.Source.from_edges("x", local), TMPL)
    assert f.ok, f.note
    assert len(f.segments) == 2, f"expected 2 segments, got {len(f.segments)}"
    assert len(f.drops) == 1, f.drops
    step = f.drops[0][1]
    assert 240 < step < 260, f"step {step:.1f} ms, expected ~250"
    print("ok   lost-count step split into segments")


def test_mixed_sources_and_rates():
    rng = np.random.default_rng(6)
    w = (T > 30) & (T < 150)
    rise = _jit(T[w & (P > 0)] - 30.0, rng)
    srcs = [_continuous("vicon", 12.0, 1000, 120, rng),
            _continuous("daq", 40.0, 2048, 90, rng),
            al.Source.from_edges("eeg", rise, polarity="rising")]
    r = al.align_recordings(srcs, mode="lags")
    assert all(f.ok for f in r.fits), [f.note for f in r.fits if not f.ok]
    assert abs(r.lag_between("vicon", "daq") - 28.0) < 0.01
    assert abs(r.lag_between("vicon", "eeg") - 18.0) < 0.01
    print("ok   mixed continuous + edge-only at 1000/2048 Hz")


def test_global_time_mode():
    rng = np.random.default_rng(7)
    srcs = [_continuous("a", 5.0, 1000, 60, rng),
            _continuous("b", 25.0, 500, 60, rng)]
    r = al.align_recordings(srcs, mode="global_time")
    ga, gb = r.global_time["a"], r.global_time["b"]
    assert abs(ga[0] - 5.0) < 0.05, ga[0]
    assert abs(gb[0] - 25.0) < 0.05, gb[0]
    # Samples are untouched: counts equal the originals.
    assert len(ga) == 60 * 1000 and len(gb) == 60 * 500
    print("ok   global_time keeps every sample, adds a common timeline")


def test_stitch_defaults():
    """Stitch upsamples to the fastest rate and leaves NaN where a source
    does not cover the timeline — never interpolating across a gap."""
    rng = np.random.default_rng(8)
    srcs = [_continuous("slow", 5.0, 500, 100, rng),
            _continuous("fast", 30.0, 2000, 40, rng)]
    r = al.align_recordings(srcs, mode="stitch")
    tb = r.table
    assert tb["fs"] == 2000, tb["fs"]
    slow_cov = np.mean(np.isfinite(tb["columns"]["slow.sync"]))
    fast_cov = np.mean(np.isfinite(tb["columns"]["fast.sync"]))
    assert slow_cov > 0.95, slow_cov
    assert 0.2 < fast_cov < 0.6, fast_cov      # covers only its own span
    print("ok   stitch upsamples to fastest rate, NaN outside coverage")


def test_short_recording_reports_clearly():
    rng = np.random.default_rng(9)
    e = _jit(T[(T > 10) & (T < 10.5)] - 10.0, rng)
    f = al.lock_source(al.Source.from_edges("x", e), TMPL)
    assert not f.ok
    assert f.note, "a failed lock must explain itself"
    print("ok   too-short recording fails with an explanation")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests)-failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

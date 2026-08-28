#!/usr/bin/env python3
"""
Self-tests for edge_sync.py. Run directly:  python3 test_edge_sync.py

Covers the failure modes that actually bit during development, so a
regression shows up as a failed assertion rather than a plausible-looking
wrong number.
"""
import sys
import numpy as np
import edge_sync as es


def _pattern(seed=0, dur=40.0):
    rng = np.random.default_rng(seed)
    tog, t = [], 0.0
    for d in rng.integers(50, 500, 4000):
        t += d / 1000.0
        if t > dur + 5:
            break
        tog.append(t)
    return np.asarray(tog), rng


def _square(tog, fs, delay_s, dur):
    tt = np.arange(int(dur * fs)) / fs
    return (np.searchsorted(tog + delay_s, tt, side="right") % 2).astype(float)


def _highpass(x, fs, tau):
    """One-pole high-pass: what an EMG amplifier does to a step."""
    a = np.exp(-1.0 / (fs * tau))
    y = np.zeros_like(x)
    for i in range(1, len(x)):
        y[i] = a * (y[i - 1] + x[i] - x[i - 1])
    return y


def test_channel_prefix_collision():
    """A short muscle name must not match the device prefix.

    Vicon labels channels 'Voltage.5-TA'. Searching the whole label for 'TA'
    hits the 'ta' in every 'Voltage.', which silently returned all 16
    channels and made plot_sync_check draw the sync channel as a muscle.
    """
    rec = es.AnalogRecording(
        fs=1000.0,
        labels=["Voltage.1-Sol", "Voltage.2-SquareDirect", "Voltage.5-TA",
                "Voltage.8-GM", "Voltage.16-SquareWirelessEmg"],
        data=np.zeros((10, 5)),
    )
    assert rec.find("TA") == [2], rec.find("TA")
    assert rec.find("Sol") == [0]
    assert rec.find("GM") == [3]
    assert len(rec.find("Square")) == 2
    # Fallback: a prefix-only pattern still matches via the full label.
    assert len(rec.find("Voltage")) == 5
    print("ok   channel prefix collision")


def test_delay_recovery():
    """Known delay through a simulated EMG amplifier, across time constants."""
    tog, rng = _pattern(seed=1)
    fs, dur, true_d = 1000.0, 40.0, 17.3
    ref = _square(tog, fs, 0.0, dur) + rng.normal(0, 0.002, int(dur * fs))
    e_ref = es.detect_edges(ref, fs)
    assert e_ref.mode == "level", e_ref.mode

    for tau_ms in (1, 5, 20):
        sig = _highpass(_square(tog, fs, true_d / 1000.0, dur), fs, tau_ms / 1000.0)
        sig = sig + rng.normal(0, 0.0012, int(dur * fs))
        e = es.detect_edges(sig, fs)
        assert e.mode == "rectified", e.mode
        r = es.edge_delay(e_ref, e, max_delay=90)
        err = r.delay_ms - true_d
        # Onset carries a small constant bias; what matters is that it does
        # not grow with the amplifier's time constant.
        assert 0.0 < err < 1.0, f"tau={tau_ms}: err {err:+.3f} ms"
        assert r.match_rate == 1.0, f"tau={tau_ms}: matched {r.match_rate:.2f}"
    print("ok   delay recovery across amplifier time constants")


def test_onset_bias_is_amplifier_independent():
    """The onset's bias must not track the amplifier; the peak's does."""
    tog, rng = _pattern(seed=2)
    fs, dur, true_d = 1000.0, 40.0, 17.3
    ref = _square(tog, fs, 0.0, dur) + rng.normal(0, 0.002, int(dur * fs))
    e_ref = es.detect_edges(ref, fs)

    onset, peak = [], []
    for tau_ms in (1, 5, 20):
        sig = _highpass(_square(tog, fs, true_d / 1000.0, dur), fs, tau_ms / 1000.0)
        sig = sig + rng.normal(0, 0.0012, int(dur * fs))
        onset.append(es.edge_delay(
            e_ref, es.detect_edges(sig, fs, locate="onset"), max_delay=90).delay_ms)
        peak.append(es.edge_delay(
            e_ref, es.detect_edges(sig, fs, locate="peak"), max_delay=90).delay_ms)

    assert max(onset) - min(onset) < 0.05, f"onset drifted with tau: {onset}"
    assert max(peak) - min(peak) > 0.20, f"peak expected to drift: {peak}"
    print("ok   onset bias independent of amplifier, peak's is not")


def test_causal_matching_rejects_negative_delays():
    """The test signal cannot precede the reference."""
    e_ref = es.Edges(np.array([1.0, 2.0]), np.array([1, -1]),
                     np.array([1.0, 1.0]), "level", 1000.0, 0.01)
    # Candidates 5 ms early and 20 ms late; only the late one is admissible.
    e_tst = es.Edges(np.array([0.995, 1.020, 2.020]), np.array([1, 1, -1]),
                     np.array([1.0, 1.0, 1.0]), "rectified", 1000.0, 0.01)
    r = es.edge_delay(e_ref, e_tst, min_delay=-2, max_delay=100)
    assert (r.deltas_ms > 0).all(), r.deltas_ms
    print("ok   causal matching rejects negative delays")


def test_polarity_is_respected():
    """A rising edge must never pair with a falling one."""
    e_ref = es.Edges(np.array([1.0]), np.array([1]),
                     np.array([1.0]), "level", 1000.0, 0.01)
    e_tst = es.Edges(np.array([1.005]), np.array([-1]),
                     np.array([1.0]), "rectified", 1000.0, 0.01)
    try:
        es.edge_delay(e_ref, e_tst, max_delay=100)
    except ValueError:
        print("ok   polarity respected (no cross-polarity match)")
        return
    raise AssertionError("a rising edge was matched to a falling one")


def test_railed_channel_flagged():
    """A disconnected sensor rails and must not pass as a large signal."""
    fs = 1000.0
    railed = np.clip(np.random.default_rng(4).normal(0, 3, 20000), -1.25, 1.25)
    q = es.process_emg(railed, fs)
    assert q["quality"]["saturated"], q["quality"]
    assert any("railed" in w for w in q["warnings"]), q["warnings"]

    clean = np.random.default_rng(5).normal(0, 0.05, 20000)
    q2 = es.process_emg(clean, fs)
    assert not q2["quality"]["saturated"]
    print("ok   railed channel flagged, clean channel not")


def test_no_spurious_edge_count_warning():
    """Cross-detector edge counts differ legitimately and must not warn.

    A level detector reports one edge per transition; a rectified detector
    reports a positive and a negative peak at each one.
    """
    tog, rng = _pattern(seed=6)
    fs, dur = 1000.0, 30.0
    ref = _square(tog, fs, 0.0, dur) + rng.normal(0, 0.002, int(dur * fs))
    sig = _highpass(_square(tog, fs, 0.02, dur), fs, 0.004)
    sig = sig + rng.normal(0, 0.0012, int(dur * fs))
    r = es.edge_delay(es.detect_edges(ref, fs), es.detect_edges(sig, fs),
                      max_delay=90)
    assert not any("edges against" in w for w in r.warnings), r.warnings
    print("ok   no spurious edge-count warning across detectors")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

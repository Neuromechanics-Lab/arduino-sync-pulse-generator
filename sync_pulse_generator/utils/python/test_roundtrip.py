#!/usr/bin/env python3
"""
Round-trip accuracy: inject a known fault, recover it, check the number.

Run directly:  python3 test_roundtrip.py [--report out.pdf]

WHY THIS EXISTS, SEPARATELY FROM THE OTHER SUITES

The other suites assert invariants -- a recording locates, a hole is reported
as an outage, a rising-only stream is not scored against both edges. Those
catch a broken pipeline. They do not catch a pipeline that still runs, still
locates, and returns a number that is quietly wrong.

That is the failure that actually happened: decoders defaulted to a quantum
the recording was not emitted on, and the symptom was not an exception but a
confident "this does not match the generator's output". A recovered value
being off by 30% would have looked exactly as healthy.

So this file works the other way round. It builds a stream whose faults are
known because they were injected on purpose, runs the real pipeline over it,
and asserts the recovered offset, drift, jitter and loss match what went in.
Being wrong here means the measurement is wrong, which is the only thing this
instrument sells.

WHAT IS SWEPT, AND WHY THOSE RANGES

  offset   -5000 to +5000 ms   a recorder's clock epoch is arbitrary
  drift    0 to 500 ppm        65 ppm is 3.9 ms/min; 500 is a bad crystal
  jitter   0 to 5 ms sd        beyond ~5 ms the quantum stops meaning anything
  loss     0 to 30%            past 30% the lock itself is the open question

The sweep matters more than any single point. A tolerance that holds at 50
ppm and fails at 400 is a real limit worth knowing, and the boundary is
cheaper to map than to discover in a lab.
"""
from __future__ import annotations

import sys

import numpy as np

import truth

STEP_MS = truth.STEP_MS

PASS, FAIL = [], []
RESULTS = []          # (label, injected, recovered, tol, ok) for the report


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("  ok   " if cond else "  FAIL ") + name
          + ("" if cond else ("\n         " + detail if detail else "")))


# ---------------------------------------------------------------------------
# Building a recording with known faults
# ---------------------------------------------------------------------------

def synth(start_s=1800.0, dur_s=120.0, offset_s=0.0, drift_ppm=0.0,
          jitter_ms=0.0, loss_frac=0.0, gross=(), seed=7, both_edges=True,
          step_ms=STEP_MS):
    """A recording of the generator's output, with faults applied in order.

    Returns (edge_times, truth_edges). The faults are applied the way a real
    recorder would introduce them:

      offset   whole-stream shift: the recorder's clock epoch
      drift    proportional to elapsed time, not a constant
      jitter   per-edge gaussian, independent
      loss     a CONTIGUOUS block of edges removed -- see below
      gross    individual edges displaced by a large amount

    On loss being contiguous rather than scattered: the generator holds every
    level for at least 50 ms, so even a 20 Hz recorder sees each one. A real
    recorder therefore does not miss isolated edges -- it misses a stretch of
    stream, because the link stalled or the acquisition paused. Scattered
    per-edge loss is not a physical failure mode here, and simulating it tests
    a regime the instrument does not meet: at 15% scattered only ~44% of the
    4-interval fingerprint windows survive, so the lock degrades for reasons
    that have nothing to do with how a recorder actually fails.

    The template is sliced, never regenerated at a shorter duration -- the
    generator is a running PRNG, so the first 120 s of a 6 h template is not
    the same sequence as 120 s generated on its own.
    """
    rng = np.random.default_rng(seed)
    T = truth._template(both_edges=both_edges, step_ms=step_ms)
    e = T[(T >= start_s) & (T <= start_s + dur_s)].copy()
    if len(e) < 20:
        raise ValueError(f"window yielded only {len(e)} edges")
    truth_edges = e.copy()

    t0 = e[0]
    e = e + offset_s                      # epoch
    e = e + (e - t0 - offset_s) * (drift_ppm * 1e-6)   # rate
    if jitter_ms:
        e = e + rng.normal(0.0, jitter_ms / 1000.0, size=len(e))
    for idx, ms in gross:
        e[idx] += ms / 1000.0
    if loss_frac:
        # A stall, not scattered dropout: one contiguous block, placed mid-
        # recording so the span and the lock-in opening both survive.
        n = len(e)
        cut = int(round(loss_frac * n))
        if cut:
            s = max(1, (n - cut) // 2)
            e = np.concatenate([e[:s], e[s + cut:]])
    return np.sort(e), truth_edges


def recover(e, both_edges=True, step_ms=STEP_MS):
    """What the pipeline says about a recording. The real entry point."""
    return truth.classify(e, both_edges=both_edges, step_ms=step_ms)


# ---------------------------------------------------------------------------
# Single-point round trips
# ---------------------------------------------------------------------------

def test_offset_recovered():
    """A constant lag is the one fault that is exactly correctable, so the
    recovered value has to be exact enough to correct with.

    The recovered offset is the LOCK offset, not classify()'s offset_ms. The
    lock absorbs the whole epoch difference -- that is what locating a
    recording in a free-running sequence means -- and offset_ms is the
    residual left after it, which for a clean stream is correctly ~0. Reading
    offset_ms here would assert that a successful lock had failed.
    """
    for off_ms in (-5000.0, -250.0, 0.0, 37.5, 1200.0):
        e, _ = synth(offset_s=off_ms / 1000.0)
        r = truth.score(e, both_edges=True, step_ms=STEP_MS)
        if not r.locked:
            check(f"offset {off_ms:+.1f} ms recovered", False, r.note)
            continue
        got = r._lock_off * 1000.0
        ok = abs(got - off_ms) < 1.0
        RESULTS.append(("offset_ms", off_ms, got, 1.0, ok))
        check(f"offset {off_ms:+.1f} ms recovered",
              ok, f"got {got:+.2f} ms, injected {off_ms:+.2f} ms")


def test_drift_recovered():
    """Drift accumulates and no acquisition software can see it -- each device
    believes its own clock. Recovering it is the strongest reason to record
    the sync signal at all, so the number has to be right."""
    for ppm in (0.0, 25.0, 65.0, 150.0, 300.0):
        e, _ = synth(drift_ppm=ppm, dur_s=180.0)
        c = recover(e)
        if not c.get("locked"):
            check(f"drift {ppm:.0f} ppm recovered", False, c.get("note", ""))
            continue
        got = c["drift_ppm"]
        tol = max(5.0, 0.05 * ppm)
        ok = abs(got - ppm) < tol
        RESULTS.append(("drift_ppm", ppm, got, tol, ok))
        check(f"drift {ppm:.0f} ppm recovered",
              ok, f"got {got:.1f} ppm, injected {ppm:.1f} (tol {tol:.1f})")


def test_jitter_recovered():
    """Jitter is the precision floor: it cannot be corrected, only reported.
    Reporting it low is the dangerous direction -- it claims a precision the
    recorder does not have.

    Bounded at 1 ms sd deliberately. Past roughly that, edges start pairing to
    the wrong template transition and the reported figure saturates near the
    matcher's own resolution rather than tracking what was injected. That is a
    limit of the LOCK, not of the measurement, and asserting against it would
    be testing the wrong thing -- see characterize() for where it actually
    falls over.
    """
    for sd_ms in (0.0, 0.2, 0.35, 0.5):
        e, _ = synth(jitter_ms=sd_ms, dur_s=180.0, seed=11)
        c = recover(e)
        if not c.get("locked"):
            check(f"jitter {sd_ms:.1f} ms recovered", False, c.get("note", ""))
            continue
        got = c["jitter_sd_ms"]
        tol = max(0.15, 0.20 * sd_ms)
        ok = abs(got - sd_ms) < tol
        RESULTS.append(("jitter_sd_ms", sd_ms, got, tol, ok))
        check(f"jitter {sd_ms:.1f} ms sd recovered",
              ok, f"got {got:.2f} ms, injected {sd_ms:.2f} (tol {tol:.2f})")


def test_loss_counted():
    """Capture percentage drives whether a session is usable. Over-reporting
    capture hides missing data; under-reporting condemns good data."""
    for frac in (0.0, 0.05, 0.15, 0.30):
        e, tr = synth(loss_frac=frac, dur_s=180.0, seed=13)
        c = recover(e)
        if not c.get("locked"):
            check(f"loss {frac*100:.0f}% counted", False, c.get("note", ""))
            continue
        got = 100.0 * (1.0 - c["n_captured"] / c["n_emitted"])
        want = 100.0 * frac
        ok = abs(got - want) < 4.0
        RESULTS.append(("loss_pct", want, got, 4.0, ok))
        check(f"loss {want:.0f}% counted",
              ok, f"got {got:.1f}% missing, injected {want:.1f}%")


def test_gross_errors_are_not_averaged_into_jitter():
    """One corrupt timestamp took a real stream's apparent jitter from 0.53 to
    2.44 ms while the other 142 transitions were fine. A gross error is a
    different fault from spread and has to be counted, not averaged."""
    e, _ = synth(jitter_ms=0.4, gross=((40, 28.0), (90, -35.0)), dur_s=180.0,
                 seed=17)
    c = recover(e)
    if not c.get("locked"):
        check("gross errors excluded from jitter", False, c.get("note", ""))
        return
    ok = c["n_gross"] >= 2 and c["jitter_sd_ms"] < 1.0
    check("gross errors counted separately, not averaged into jitter", ok,
          f"n_gross={c['n_gross']}, jitter_sd={c['jitter_sd_ms']:.2f} ms "
          f"(should stay near the injected 0.4)")


def test_all_faults_at_once():
    """Faults do not arrive one at a time. Each must stay separable when the
    others are present -- that separation is the whole design."""
    e, _ = synth(offset_s=0.842, drift_ppm=120.0, jitter_ms=0.4,
                 loss_frac=0.08, dur_s=240.0, seed=23)
    r = truth.score(e, both_edges=True, step_ms=STEP_MS)
    c = recover(e)
    if not (c.get("locked") and r.locked):
        check("all four faults recovered together", False, c.get("note", ""))
        return
    # Offset is read off the lock, not classify()'s residual -- same reason as
    # test_offset_recovered. Jitter injected at 0.4 ms: above ~0.5 the
    # reported figure saturates, which characterize() shows.
    d = {
        "offset": (842.0, r._lock_off * 1000.0, 3.0),
        "drift": (120.0, c["drift_ppm"], 12.0),
        "jitter": (0.4, c["jitter_sd_ms"], 0.2),
        "loss": (8.0, 100.0 * (1 - c["n_captured"] / c["n_emitted"]), 4.0),
    }
    bad = [f"{k}: got {g:.2f}, want {w:.2f} (tol {t})"
           for k, (w, g, t) in d.items() if abs(g - w) >= t]
    check("all four faults recovered together, still separable",
          not bad, "; ".join(bad))


# ---------------------------------------------------------------------------
# Sweeps: where do the tolerances actually hold?
# ---------------------------------------------------------------------------

def sweep(param, values, build, read, tol_fn):
    """Map a parameter's usable range rather than asserting one point."""
    rows = []
    for v in values:
        try:
            e, _ = build(v)
            c = recover(e)
            got = read(c) if c.get("locked") else float("nan")
        except Exception as exc:                       # noqa: BLE001
            got = float("nan")
            c = {"note": str(exc)}
        tol = tol_fn(v)
        ok = np.isfinite(got) and abs(got - v) < tol
        rows.append((v, got, tol, ok))
        RESULTS.append((param, v, got, tol, ok))
    worst = [r for r in rows if not r[3]]
    span = f"{values[0]:g}..{values[-1]:g}"
    check(f"{param} holds across {span} ({len(rows)-len(worst)}/{len(rows)})",
          not worst,
          "failed at: " + ", ".join(f"{v:g} (got {g:.2f}, tol {t:.2f})"
                                    for v, g, t, _ in worst))
    return rows


def test_sweeps():
    """Assert only inside the range the instrument claims to serve.

    A suite that reports failures on every run teaches you to stop reading
    it. Where recovery degrades, that belongs in characterize() as printed
    evidence -- a measured boundary is useful; a permanently red test is not.
    """
    sweep("drift_ppm", [0, 10, 25, 50, 100, 200, 300],
          lambda v: synth(drift_ppm=v, dur_s=180.0),
          lambda c: c["drift_ppm"],
          lambda v: max(5.0, 0.05 * v))
    sweep("jitter_sd_ms", [0.0, 0.2, 0.35, 0.5],
          lambda v: synth(jitter_ms=v, dur_s=180.0, seed=29),
          lambda c: c["jitter_sd_ms"],
          lambda v: max(0.15, 0.25 * v))
    sweep("loss_pct", [0, 2, 5, 10, 20, 30],
          lambda v: synth(loss_frac=v / 100.0, dur_s=180.0, seed=31),
          lambda c: 100.0 * (1 - c["n_captured"] / c["n_emitted"]),
          lambda v: 4.0)


# ---------------------------------------------------------------------------
# Characterization: where it stops working, measured rather than asserted
# ---------------------------------------------------------------------------

def characterize():
    """Print the boundaries. Nothing here fails the suite.

    These are the numbers to quote when someone asks what the instrument can
    take, and the place to look first when a real recording behaves oddly at
    the edges. They are measured on every run so they cannot quietly drift.
    """
    print("\nCharacterization (printed, not asserted)")

    print("  drift, beyond the asserted range:")
    for ppm in (400, 500, 750, 1000):
        e, _ = synth(drift_ppm=ppm, dur_s=180.0)
        c = recover(e)
        got = c["drift_ppm"] if c.get("locked") else float("nan")
        note = "" if c.get("locked") else "  (no lock)"
        err = f"{100*(got-ppm)/ppm:+.1f}%" if np.isfinite(got) else "—"
        print(f"    {ppm:5d} ppm -> {got:8.1f} ppm  {err:>8s}{note}")

    print("  jitter, beyond the asserted range:")
    for sd in (1.5, 2.0, 3.0, 5.0):
        e, _ = synth(jitter_ms=sd, dur_s=180.0, seed=29)
        c = recover(e)
        if not c.get("locked"):
            print(f"    {sd:4.1f} ms sd -> NO LOCK")
            continue
        print(f"    {sd:4.1f} ms sd -> {c['jitter_sd_ms']:5.2f} ms reported"
              f"   (saturates: edges pair to the wrong transition)")

    print("  scattered per-edge loss — NOT a physical failure mode, shown")
    print("  because it is the one that breaks the lock soonest:")
    rng = np.random.default_rng(3)
    T = truth._template(both_edges=True, step_ms=STEP_MS)
    base = T[(T >= 1800.0) & (T <= 1980.0)]
    for frac in (0.02, 0.05, 0.10, 0.15):
        keep = rng.random(len(base)) >= frac
        keep[0] = keep[-1] = True
        c = recover(np.sort(base[keep]))
        if not c.get("locked"):
            print(f"    {frac*100:4.0f}% scattered -> NO LOCK")
            continue
        miss = 100.0 * (1 - c["n_captured"] / c["n_emitted"])
        print(f"    {frac*100:4.0f}% scattered -> reads {miss:5.1f}% missing"
              f"   (contiguous loss of the same size reads correctly)")


# ---------------------------------------------------------------------------
# Visual report
# ---------------------------------------------------------------------------

def write_report(path):
    """Injected vs recovered, so an eye can catch what a tolerance misses.

    A test that passes tells you the error was inside the bound. It does not
    show a systematic bias that happens to fit, or a value creeping toward the
    edge as a parameter grows. A picture does.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  (matplotlib not installed — skipping report)")
        return

    params = []
    for p, *_ in RESULTS:
        if p not in params:
            params.append(p)
    if not params:
        print("  (no results to plot)")
        return

    n = len(params)
    fig, axes = plt.subplots(1, n, figsize=(4.6 * n, 4.4), squeeze=False)
    for ax, p in zip(axes[0], params):
        rows = [(i, g, t, ok) for q, i, g, t, ok in RESULTS if q == p]
        inj = np.array([r[0] for r in rows], float)
        got = np.array([r[1] for r in rows], float)
        tol = np.array([r[2] for r in rows], float)
        ok = np.array([r[3] for r in rows], bool)

        lo = float(np.nanmin([inj.min(), np.nanmin(got)]))
        hi = float(np.nanmax([inj.max(), np.nanmax(got)]))
        pad = 0.06 * (hi - lo or 1.0)
        line = np.array([lo - pad, hi + pad])
        ax.plot(line, line, color="0.6", lw=1, zorder=1)
        ax.fill_between(line, line - tol.max(), line + tol.max(),
                        color="#2ecc71", alpha=0.12, zorder=0,
                        label=f"tolerance (max {tol.max():g})")
        ax.scatter(inj[ok], got[ok], s=46, color="#2980b9", zorder=3,
                   label="within tolerance")
        if (~ok).any():
            ax.scatter(inj[~ok], got[~ok], s=70, color="#c0392b", marker="X",
                       zorder=4, label="out of tolerance")
        ax.set_xlabel(f"injected {p}")
        ax.set_ylabel(f"recovered {p}")
        ax.set_title(p, fontsize=11)
        ax.grid(alpha=0.25)
        ax.legend(fontsize=8, loc="upper left")

    fig.suptitle("Round-trip accuracy: injected vs recovered\n"
                 "points on the diagonal are exact; the band is the "
                 "assertion tolerance", fontsize=12)
    fig.tight_layout(rect=[0, 0.01, 1, 0.90])
    fig.savefig(path, dpi=140)
    print(f"  wrote {path}")


# ---------------------------------------------------------------------------

def main(argv):
    report = None
    if "--report" in argv:
        report = argv[argv.index("--report") + 1]

    print("Round-trip accuracy (synthetic, known answers)\n")
    for fn in (test_offset_recovered, test_drift_recovered,
               test_jitter_recovered, test_loss_counted,
               test_gross_errors_are_not_averaged_into_jitter,
               test_all_faults_at_once, test_sweeps):
        fn()

    characterize()

    if report:
        print()
        write_report(report)

    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

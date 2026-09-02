"""
signal - regenerate the emitted waveform, and read its embedded timecode.

The foundation every other stage rests on. Because the generator's output is
fully determined by (seed, configuration), the waveform that was physically on
the wire can be reproduced offline and used as ground truth.

Two things live here:

  the TEMPLATE   what the generator emitted, as transition times
  the TIMECODE   frames embedded in that signal carrying a run ID and the
                 elapsed second, which give absolute position with no search
"""

from __future__ import annotations
import numpy as np

# Firmware configuration (config.h). Fixed for this lab; pass explicitly to
# override. These are not guesses — a recording that does not match them is
# telling you the box was configured differently.
SEED = 42
MIN_MS = 50
MAX_MS = 500
STEP_MS = 5          # the generator's quantum: it can emit nothing finer
TC_INTERVAL_S = 10

# How far into a free-running session to search by default. A box left running
# all morning is deep into its sequence by the afternoon.
SEARCH_HOURS = 6.0

_CACHE: dict = {}


def template(duration_s=None, seed=SEED, tc_enabled=False,
             tc_interval_s=TC_INTERVAL_S, run_id=1, hours=None):
    """Transition times and levels of the emitted waveform.

    Cached, because the template depends only on its arguments and is
    identical for every stream in a session; regenerating six hours of it per
    stream once dominated the runtime.
    """
    if duration_s is None:
        duration_s = (hours if hours is not None else SEARCH_HOURS) * 3600
    key = (round(duration_s), seed, bool(tc_enabled), tc_interval_s, run_id)
    if key in _CACHE:
        return _CACHE[key]

    from . import _timecode as tcmod
    times, levels = tcmod.generate_template(
        seed=seed, duration_s=duration_s,
        min_high=MIN_MS, max_high=MAX_MS, min_low=MIN_MS, max_low=MAX_MS,
        tc_enabled=tc_enabled, tc_interval_s=tc_interval_s, run_id=run_id)
    out = (np.asarray(times, float) / 1000.0, np.asarray(levels, int))
    _CACHE[key] = out
    return out


def template_edges(both_edges=True, **kw):
    """Just the transition times.

    both_edges=False returns rises only, for comparison against a trigger line
    that logs one polarity. Using both against such a stream doubles every
    interval and nothing matches.
    """
    t, lv = template(**kw)
    return t if both_edges else t[lv == 1]


def decode_frames(edge_times, edge="rising", tol_ms=3.0):
    """Timecode frames present in a recorded edge stream.

    A frame carries [16-bit run ID][32-bit elapsed seconds][4-bit checksum] in
    pulse timing. Where one survives it beats any pattern search: it states
    the position outright, checksum-verified, and it is the only thing that
    identifies WHICH RUN was recorded — a fixed seed makes every run's
    waveform identical.

    Needs a single-polarity stream. Frame pulses have constant width, so
    rising-only and falling-only both decode, but an interleaved list halves
    every interval and decodes nothing.
    """
    from . import _timecode as tcmod
    return tcmod.decode_frames(sorted(np.asarray(edge_times, float).tolist()),
                               edge=edge, tol_ms=tol_ms)


def split_runs(frames):
    """Group decoded frames by run ID.

    A run ID change is a hard boundary: each run counts elapsed time from its
    own zero, so frames either side cannot be placed on one timeline.
    """
    from . import _timecode as tcmod
    return tcmod.split_runs(frames)

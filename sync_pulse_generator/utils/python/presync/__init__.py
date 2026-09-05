"""
presync - recover trustworthy timing from recordings of the PRE-Sync signal.

The generator emits a pseudo-random square wave whose every transition is
determined by (seed, configuration). That makes the emitted waveform
reproducible offline, so it can be regenerated and used as ground truth:
each recorded edge has a known true time, and the difference is the
recorder's error.

The pipeline, in the order a full analysis runs them:

    load -> locate -> score -> chunk -> judge -> compare -> report

  load     recording file -> edge times (XDF, C3D, CSV)
  events   decode the event channel: which trigger, and exactly when
  locate   find where the recording sits in the generator's sequence
  score    offset, drift, jitter, capture, loss -- against the template
  chunk    per-window quality, on timecode frames where present
  judge    turn the numbers into findings a person can act on
  compare  streams against each other, once each is scored on its own
  report   text and PDF

One call runs all of it:

    presync.analyze_file("session.xdf")          # -> Analysis
    python -m presync run session.xdf --pdf out.pdf

This package is an organisation of existing, verified code. The analysis
functions live in the modules alongside it (truth, align, analyze, edge_sync,
timecode, diagnose) and are re-exported here so there is one obvious entry
point per stage rather than five overlapping ones.
"""

__version__ = "1.0.0"

# ---- stage 1: load -----------------------------------------------------
from analyze import Stream, load_xdf
from edge_sync import (load_c3d_analog, detect_edges, edge_delay,
                       sync_report, process_emg, shift_timestamps)

# ---- stage 2: locate ---------------------------------------------------
from timecode import (generate_template, decode_frames, align_to_timecode,
                      split_runs, frame_durations, checksum4)
from align import build_template, find_start, decode_source_frames

# ---- stage 3: score ----------------------------------------------------
from truth import (score, classify, correct, compare as compare_reports,
                   report as truth_report, TruthReport,
                   SEED, STEP_MS, SEARCH_HOURS)

# ---- stages 4-6: chunk, judge, compare ---------------------------------
from analyze import (analyze_streams, analyze_file, Analysis, StreamResult)

# ---- alignment / resampling -------------------------------------------
from align import (Source, Fit, AlignResult, lock_source, align_recordings,
                   score_against_truth)

# ---- event channel -----------------------------------------------------
from events import (decode_events, event_report, Event,
                    MARK_MS, GAP_MS, BIT0_MS, BIT1_MS, COUNTER_BITS)

# ---- pairwise diagnosis ------------------------------------------------
from diagnose import Recording, PairReport, diagnose_pair

from .runner import run

__all__ = [
    "run", "analyze_file", "analyze_streams", "Analysis", "StreamResult",
    "Stream", "load_xdf", "load_c3d_analog", "detect_edges", "edge_delay",
    "sync_report", "process_emg", "shift_timestamps",
    "generate_template", "decode_frames", "align_to_timecode", "split_runs",
    "frame_durations", "checksum4", "build_template", "find_start",
    "decode_source_frames",
    "score", "classify", "correct", "compare_reports", "truth_report",
    "TruthReport", "SEED", "STEP_MS", "SEARCH_HOURS",
    "decode_events", "event_report", "Event",
    "MARK_MS", "GAP_MS", "BIT0_MS", "BIT1_MS", "COUNTER_BITS",
    "Source", "Fit", "AlignResult", "lock_source", "align_recordings",
    "score_against_truth", "Recording", "PairReport", "diagnose_pair",
    "__version__",
]

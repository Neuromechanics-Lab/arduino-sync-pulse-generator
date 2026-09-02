"""
presync - analysis toolkit for recordings carrying the PRE-Sync signal.

The signal is deterministic, so the waveform that was on the wire can be
regenerated exactly. That makes it GROUND TRUTH: every recording is judged
against what the generator emitted, not against another recording — which
matters because comparing two recordings cannot say which of them is at
fault, and on real data both were.

STAGES, in the order they have to run. Each does one thing and each is
callable on its own:

    signal    regenerate the emitted waveform; decode timecode frames
    detect    waveform or event stream  ->  transition times
    locate    find where a recording sits in the generator's run
    measure   offset, drift, jitter, gross errors, outages — kept separate
    combine   place several recordings on one timeline; stitch or annotate
    report    text and PDF

    run       all of the above, in order, from a file

    io        loaders (XDF, C3D, Nexus CSV)
    emg       EMG processing — not sync analysis, but it travels with it

Quick start:

    import presync
    rep = presync.run("recording.xdf")
    print(rep)
    rep.to_pdf("report.pdf")

or from the shell:

    python -m presync run recording.xdf --pdf report.pdf
    python -m presync locate recording.xdf
    python -m presync measure recording.xdf

WHY THE STAGES ARE SPLIT THIS WAY

Each boundary is one that was crossed wrongly at least once while building
this, and the errors were silent rather than loud:

  * locate is separate from measure because the generator is usually ALREADY
    RUNNING when recording starts. Two real recordings from one continuous
    run sat 17.9 and 41.1 minutes in; code that assumed t=0 reported "no seed
    matches" on a perfect file.

  * measure reports four faults separately because lumping them made the same
    recording read anywhere from 0.5 to 2.6 ms of "jitter" depending on how it
    was sliced. Offset is correctable exactly; drift is correctable but
    accumulates and is invisible to acquisition software; jitter is the
    irreducible floor; outages and corrupt timestamps are not timing errors at
    all.

  * detect is separate from locate because a trigger line logging brief pulses
    and an analog channel carrying the whole wave need different edge
    extraction but the same downstream analysis.
"""

__version__ = "1.0.0"

from .signal import (
    template, template_edges, decode_frames, split_runs,
    SEED, STEP_MS, MIN_MS, MAX_MS,
)
from .detect import edges_from_waveform, edges_from_events
from .locate import locate, Location
from .measure import measure, Measurement, correct
from .combine import combine, Combined
from .report import Report, to_pdf
from .runner import run, run_streams, Stream

__all__ = [
    "template", "template_edges", "decode_frames", "split_runs",
    "edges_from_waveform", "edges_from_events",
    "locate", "Location",
    "measure", "Measurement", "correct",
    "combine", "Combined",
    "Report", "to_pdf",
    "run", "run_streams", "Stream",
    "SEED", "STEP_MS", "MIN_MS", "MAX_MS",
]

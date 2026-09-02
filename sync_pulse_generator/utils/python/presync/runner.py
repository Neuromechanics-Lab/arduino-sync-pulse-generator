"""
runner - the whole pipeline, in the right order.

  detect -> locate -> measure -> combine -> report

The stages are usable on their own, and sometimes should be. But the order
matters and the failure at each step is specific, so this exists so that the
normal case is one call and nobody has to remember that locating comes before
measuring or that streams must be scored independently before being compared.
"""

from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from .locate import locate
from .measure import measure
from .combine import combine
from .report import Report, to_pdf
from .signal import SEARCH_HOURS


@dataclass
class Stream:
    """One recorded stream, already reduced to edge times."""
    name: str
    edge_times: np.ndarray
    both_edges: bool = True   # False for a device logging one polarity only


def run_streams(streams, hours=SEARCH_HOURS, seed=None, source="",
                lsl_offsets=None, pdf=None, verbose=True):
    """Run the pipeline over already-detected streams."""
    ms = []
    for s in streams:
        if verbose:
            print(f"  locating {s.name} ...", flush=True)
        loc = locate(s.edge_times, both_edges=s.both_edges, seed=seed,
                     hours=hours)
        ms.append(measure(s.edge_times, both_edges=s.both_edges, name=s.name,
                          location=loc, seed=seed, hours=hours))
    rep = Report(measurements=ms, combined=combine(ms), source=source,
                 lsl_offsets=lsl_offsets or {})
    if pdf:
        to_pdf(rep, pdf)
        if verbose:
            print(f"  wrote {pdf}")
    return rep


def run(path, hours=SEARCH_HOURS, seed=None, keep=None, pdf=None,
        both_edges=None, verbose=True):
    """Run the pipeline on a recording file. Format is chosen by extension."""
    from . import io as _io
    p = str(path)
    offsets = {}
    if p.lower().endswith(".xdf"):
        loaded, offsets = _io.load_xdf(p, keep=keep)
        streams = [
            Stream(name, e,
                   both_edges=(kind == "continuous") if both_edges is None
                   else both_edges)
            for name, e, kind in loaded]
    elif p.lower().endswith(".c3d"):
        e, kind = _io.load_c3d(p, channel=keep[0] if keep else None)
        streams = [Stream(keep[0] if keep else "c3d", e,
                          both_edges=True if both_edges is None else both_edges)]
    elif p.lower().endswith(".csv"):
        e, kind = _io.load_csv(p)
        streams = [Stream("csv", e,
                          both_edges=(kind == "continuous")
                          if both_edges is None else both_edges)]
    else:
        raise ValueError(f"unrecognised file type: {p}")
    return run_streams(streams, hours=hours, seed=seed, source=p,
                       lsl_offsets=offsets, pdf=pdf, verbose=verbose)

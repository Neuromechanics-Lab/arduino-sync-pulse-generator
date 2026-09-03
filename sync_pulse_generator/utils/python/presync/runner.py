"""
runner - the whole analysis, in the right order.

The stages are individually useful, but the order matters and each has its
own failure. This exists so the normal case is one call, and so nobody has to
remember that the clock offset is applied at load time, or that streams are
scored against the generator before they are compared with each other.
"""

from __future__ import annotations
import analyze


def run(*paths, chunk_s=10.0, pdf=None, verbose=True):
    """Full analysis of one or more recordings that share the sync signal.

    Returns the Analysis. With pdf=, also writes the report with figures.
    """
    A = analyze.analyze_file(*paths, chunk_s=chunk_s, verbose=verbose)
    if pdf:
        analyze._pdf(A, pdf)
        if verbose:
            print(f"  wrote {pdf}")
    return A

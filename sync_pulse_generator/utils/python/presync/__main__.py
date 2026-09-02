"""Command line entry: python -m presync <file> [--pdf out.pdf]"""
import argparse
import numpy as np
from .runner import run
from .locate import locate
from .measure import measure


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="presync",
        description="Analyse a recording against the PRE-Sync emitted signal.")
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("run", help="full pipeline: locate, measure, report")
    r.add_argument("file")
    r.add_argument("--pdf", help="also write a PDF report here")
    r.add_argument("--hours", type=float, default=6.0,
                   help="how far into the generator's run to search")
    r.add_argument("--seed", type=int, default=None)
    r.add_argument("--stream", action="append", dest="keep",
                   help="restrict to this stream (repeatable)")
    r.add_argument("--rising-only", action="store_true",
                   help="force single-polarity matching for every stream")

    l = sub.add_parser("locate", help="only report where a recording sits")
    l.add_argument("file")
    l.add_argument("--hours", type=float, default=6.0)

    a = p.parse_args(argv)
    if a.cmd == "locate":
        rep = run(a.file, hours=a.hours, verbose=False)
        for m in rep.measurements:
            lo = m.location
            print(f"{m.name:<24} " + (
                f"{lo.method:<12} +{lo.offset_s:9.1f}s  "
                f"{lo.coverage_pct:5.1f}% placed"
                if lo and lo.found else "NOT LOCATED"))
        return 0

    if a.cmd == "run" or a.cmd is None:
        if a.cmd is None:
            p.print_help()
            return 1
        rep = run(a.file, hours=a.hours, seed=a.seed, keep=a.keep, pdf=a.pdf,
                  both_edges=False if a.rising_only else None)
        print(rep.text())
        return 0
    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

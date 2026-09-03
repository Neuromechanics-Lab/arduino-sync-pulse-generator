"""Command line entry: python -m presync run <files...> [--pdf out.pdf]"""
import argparse
from .runner import run


def main(argv=None):
    p = argparse.ArgumentParser(
        prog="presync",
        description="Analyse recordings against the emitted PRE-Sync signal.")
    sub = p.add_subparsers(dest="cmd")

    r = sub.add_parser("run", help="full analysis: locate, score, report")
    r.add_argument("files", nargs="+")
    r.add_argument("--pdf", help="also write a PDF report here")
    r.add_argument("--chunk", type=float, default=10.0,
                   help="chunk length in seconds (default 10)")

    a = p.parse_args(argv)
    if a.cmd != "run":
        p.print_help()
        return 1
    A = run(*a.files, chunk_s=a.chunk, pdf=a.pdf, verbose=True)
    print(A)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

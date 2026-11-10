"""python -m cssynth target.png  ->  prints HTML/CSS that draws the target."""
import argparse
import os
import sys

from .compiler import RHO, compile_image


def main():
    ap = argparse.ArgumentParser(prog="cssynth", description=__doc__)
    ap.add_argument("image")
    ap.add_argument("-v", action="store_true", help="log the search")
    ap.add_argument("--rho", type=float, default=RHO,
                    help="wrong pixels accepted per character saved (default %(default)s)")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count(),
                    help="processes for the search variants (default: all cores)")
    ap.add_argument("--fast", action="store_true",
                    help="skip re-searching parts of the result (several times faster, a little longer code)")
    ap.add_argument("--research", type=int, default=1, metavar="N",
                    help="re-search the N best results, not only the best (default %(default)s; 3 lowered the "
                         "benchmark's J by about 2%% for 1.5 to 2 times the CPU)")
    args = ap.parse_args()
    code, info, _ = compile_image(args.image, rho=args.rho, research=0 if args.fast else args.research, jobs=args.jobs,
                                  log=(lambda m: print(m, file=sys.stderr)) if args.v else None)
    print(code)
    print(f"{len(code)} chars, {info}", file=sys.stderr)


if __name__ == "__main__":
    main()

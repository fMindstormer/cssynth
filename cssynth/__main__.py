"""python -m cssynth target.png  ->  prints HTML/CSS that draws the target."""
import argparse
import sys

from .compiler import RHO, compile_image


def main():
    ap = argparse.ArgumentParser(prog="cssynth", description=__doc__)
    ap.add_argument("image")
    ap.add_argument("-v", action="store_true", help="log the search")
    ap.add_argument("--rho", type=float, default=RHO,
                    help="wrong pixels accepted per character saved (default %(default)s)")
    args = ap.parse_args()
    code, info, _ = compile_image(args.image, rho=args.rho,
                                  log=(lambda m: print(m, file=sys.stderr)) if args.v else None)
    print(code)
    print(f"{len(code)} chars, {info}", file=sys.stderr)


if __name__ == "__main__":
    main()

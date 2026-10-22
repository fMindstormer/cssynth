#!/usr/bin/env python3
"""A tiny benchmark whose optimal programs are known, to measure how far the
search is from optimal.

    python bench/tiny.py [--n 30] [--jobs 8]      # writes bench/tiny.json

The space S: a background color and up to four shapes, each a box or an
ellipse whose edges lie on a 10 px grid inside the canvas, each in its own
color (none the background's). Targets are random stacks from S. For each
one, an exact solver lists every stack in S that draws the same pixels and
takes the shortest code cssynth's own emitter writes for any of them. So
the optimum and cssynth's output are written by the same emitter, and the
gap measures the search alone.

The solver works from the top of the stack down. With one shape per color,
a shape of color c must cover every pixel of color c, and may cover other
pixels only where shapes above it hide them. So for each order of the
colors, each level's candidates are the grid shapes that contain the
pixels of its color and stay inside them plus what is already covered.
Containment is checked exactly with the search's own gain tables.

Pixels are cssynth's model (shapes.render_labels and render_rgb), not a
browser: this benchmark isolates the search from rendering differences.
cssynth may also find code outside S (box-shadows, a shape in the
background color); then the "gap" can be negative.
"""

import argparse
import itertools
import json
import random
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cssynth.codegen import emit  # noqa: E402
from cssynth.compiler import RHO, compile_image  # noqa: E402
from cssynth.search import area_sums, gain  # noqa: E402
from cssynth.shapes import H, Shape, W, render_labels, render_rgb  # noqa: E402

GRID = 10
SEED = 7
COLORS = ["#1a4341", "#998235", "#f3ac3c", "#62374e", "#fdc57b", "#e3516e", "#293462", "#f7d716",
          "#e8e7ce", "#c55b3d", "#b5e0ba", "#6592cf"]


def rgb(h):
    return [int(h[i:i + 2], 16) for i in (1, 3, 5)]


def generate(seed):
    """(palette, shapes): a background (index 0) and 1-4 shapes from S, each
    showing at least 200 pixels."""
    R = random.Random(seed)
    while True:
        k = R.choice([1, 2, 3, 3, 4, 4])
        pal = np.array([rgb(h) for h in R.sample(COLORS, k + 1)])
        shapes = []
        for c in range(1, k + 1):
            w, h = GRID * R.randint(3, 25), GRID * R.randint(3, 22)
            x, y = GRID * R.randint(0, (W - w) // GRID), GRID * R.randint(0, (H - h) // GRID)
            shapes.append(Shape(x, y, w, h, c, ell=R.random() < 0.5))
        L = render_labels(0, shapes)
        if all((L == c).sum() >= 200 for c in range(1, k + 1)):
            return pal, shapes


def _boxes_around(need):
    """Every grid box (x0, y0, x1, y1) inside the canvas that contains need's
    bounding box, as arrays."""
    ys, xs = np.nonzero(need)
    x0s = np.arange(0, xs.min() + 1, GRID)
    x1s = np.arange(-(-(xs.max() + 1) // GRID) * GRID, W + 1, GRID)
    y0s = np.arange(0, ys.min() + 1, GRID)
    y1s = np.arange(-(-(ys.max() + 1) // GRID) * GRID, H + 1, GRID)
    g = np.meshgrid(x0s, y0s, x1s, y1s, indexing="ij")
    return [a.ravel() for a in g]


def candidates(c, need, allowed):
    """Grid shapes of color c that cover all of need and nothing outside allowed."""
    bad = ~allowed
    S = np.zeros((H + 1, W + 1), dtype=np.int32)
    S[1:, 1:] = bad.cumsum(0).cumsum(1)
    x0, y0, x1, y1 = _boxes_around(need)
    inside = (S[y1, x1] - S[y0, x1] - S[y1, x0] + S[y0, x0]) == 0
    out = [Shape(int(a), int(b), int(c2 - a), int(d - b), c) for a, b, c2, d in
           zip(x0[inside], y0[inside], x1[inside], y1[inside])]
    # An ellipse fits only if the pixels just below its center, across all
    # but the end pixel each way, do: on the grid (sizes >= 10) the ellipse
    # covers them. That is the cheap test; then exactly: the gain against
    # (need, bad) equals |need| iff it covers all of need and none of bad.
    sums, n_need = area_sums(need, bad), int(need.sum())
    my, mx = (y0 + y1) // 2, (x0 + x1) // 2
    row = (S[my + 1, x1 - 1] - S[my, x1 - 1] - S[my + 1, x0 + 1] + S[my, x0 + 1]) == 0
    col = (S[y1 - 1, mx + 1] - S[y0 + 1, mx + 1] - S[y1 - 1, mx] + S[y0 + 1, mx]) == 0
    for a, b, c2, d in zip(*(v[row & col] for v in (x0, y0, x1, y1))):
        s = Shape(int(a), int(b), int(c2 - a), int(d - b), c, ell=True)
        if gain(s, need, bad, sums) == n_need:
            out.append(s)
    return out


def solve(L, k, cap=200_000):
    """All stacks in S that draw labels L (colors 1..k over background 0),
    top first, or None past cap."""
    stacks = []
    for order in itertools.permutations(range(1, k + 1)):
        def rec(i, covered, above):
            if len(stacks) > cap:
                return
            if i == k:
                stacks.append(list(reversed(above)))       # bottom first, as the compiler stacks them
                return
            c = order[i]
            need = L == c
            for s in candidates(c, need, need | covered):
                m = render_labels(-1, [s]) >= 0
                rec(i + 1, covered | m, above + [s])
        rec(0, np.zeros((H, W), dtype=bool), [])
    return None if len(stacks) > cap else stacks


def optimum(pal, stacks):
    """(length, code) of the shortest emitted stack."""
    best = min((emit(pal, 0, st)[0] for st in stacks), key=len)
    return len(best), best


def work(seed):
    pal, shapes = generate(seed)
    L = render_labels(0, shapes)
    k = len(shapes)
    t = time.time()
    stacks = solve(L, k)
    n_opt, opt_code = optimum(pal, stacks)
    t_solve = time.time() - t
    ref_code = emit(pal, 0, shapes)[0]
    t = time.time()
    code, info, (cpal, cbg, _, cshapes) = compile_image(Image.fromarray(render_rgb(0, pal, shapes)))
    t_compile = time.time() - t
    # wrong pixels in cssynth's own model: its labels, as colors, against the target's
    got = np.asarray(cpal)[render_labels(cbg, cshapes)] if not hasattr(cbg, "stops") else None
    wrong = int((np.abs(got - pal[L]).max(2) > 8).sum()) if got is not None else None
    return {"seed": seed, "shapes": k, "kinds": ["ellipse" if s.ell else "box" for s in shapes],
            "stacks": len(stacks), "optimal": n_opt, "optimal_code": opt_code, "reference": len(ref_code),
            "cssynth": len(code), "cssynth_code": code, "cssynth_wrong": wrong,
            "J_cssynth": len(code) + (wrong or 0) / RHO, "solve_s": round(t_solve, 1),
            "compile_s": round(t_compile, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--out", default=str(ROOT / "bench" / "tiny.json"))
    args = ap.parse_args()
    seeds = [SEED * 1000 + i for i in range(args.n)]
    with Pool(args.jobs) as p:
        res = p.map(work, seeds, chunksize=1)
    Path(args.out).write_text(json.dumps(res, indent=1))
    exact = [r for r in res if r["cssynth_wrong"] == 0]
    print(f"{len(res)} targets; cssynth exact on {len(exact)}")
    for r in res:
        print(f"seed {r['seed']}  {r['shapes']} shapes  {r['stacks']:6d} stacks  optimal {r['optimal']:4d}  "
              f"cssynth {r['cssynth']:4d} ({r['cssynth_wrong']} wrong)  gap {r['cssynth'] - r['optimal']:+d}")
    gaps = [r["cssynth"] - r["optimal"] for r in exact]
    if gaps:
        print(f"on exact outputs: optimal on {sum(g <= 0 for g in gaps)}/{len(gaps)}, "
              f"mean gap {np.mean(gaps):+.1f} chars, total {sum(r['cssynth'] for r in exact)} vs "
              f"{sum(r['optimal'] for r in exact)}")


if __name__ == "__main__":
    main()

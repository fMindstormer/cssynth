#!/usr/bin/env python3
"""Generated targets in structural families, for testing generalization.

    python bench/families.py heldout      # bench/heldout/: cases.json, <id>.html, <id>.png
    python bench/families.py heldout2     # a second held-out set (bench/heldout2/)
    python bench/families.py train N      # N per family to a scratch directory (see --out)

Each target is drawn by a short CSS program built from one family's
structure:

  mirror   a shape and its mirror image across the canvas's center line,
           sometimes with a centered shape between them
  repeat   copies of one shape at a constant offset (a row or a grid)
  rings    concentric circles or squares in alternating colors
  petals   leaves turned about a common center at equal angles
  stripes  bands across the canvas with an emblem on top
  scatter  unrelated shapes in layers (the control: no shared structure)

The program's length is a reference, like the human solutions' length on
the development set: no attempt is made to golf it. The held-out sets are
made from fixed seeds and are not used while developing the compiler; each
is compiled once per version under test. The first was spent on the first
version of the motif work (docs/method.md), the second on the revised one.
"""

import argparse
import json
import math
import random
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"
FAMILIES = ("mirror", "repeat", "rings", "petals", "stripes", "scatter")
HELDOUT_SEEDS = {"heldout": 20261021, "heldout2": 20261121, "heldout3": 20261221}
PER_FAMILY = 8

PALETTES = [
    ("#1a4341", "#998235", "#f3ac3c"), ("#62374e", "#fdc57b", "#e3516e"), ("#0b2429", "#f3ac3c", "#998235"),
    ("#293462", "#f7d716", "#ec9b3b"), ("#222730", "#e8e7ce", "#c55b3d"), ("#5d3a3a", "#b5e0ba", "#ffffff"),
    ("#191919", "#ff6a6a", "#ffe08f"), ("#0f2b34", "#6592cf", "#eeb850"), ("#4f77ff", "#ffffff", "#222222"),
    ("#e3516e", "#51b5a9", "#fade8b"),
]


def box(x, y, w, h, color, radius=None, rot=None, extra=""):
    s = f"position:fixed;left:{x}px;top:{y}px;width:{w}px;height:{h}px;background:{color}"
    if radius:
        s += f";border-radius:{radius}"
    if rot:
        s += f";rotate:{rot}deg"
    return f'<p style="{s}{extra}"></p>'


def page(bg, elements):
    return f'<body style="margin:0;background:{bg}">' + "".join(elements)


def snap(R, lo, hi, q=5):
    return q * R.randint(-(-lo // q), hi // q)


def _shape_kind(R, w, h):
    """A radius (or None) for a box of size w x h."""
    k = R.random()
    if k < 0.35:
        return "50%"
    if k < 0.55:
        return None
    if k < 0.75:
        return f"{snap(R, 5, min(w, h) // 2)}px"
    return f"{min(w, h)}px 0" if k < 0.9 else f"0 0 {w // 2}px {w // 2}px"


def mirror(R, pal):
    bg, a, b = pal
    w, h = snap(R, 30, 120), snap(R, 30, 160)
    x = snap(R, 10, 190 - w)
    y = snap(R, 20, 280 - h)
    rad = _shape_kind(R, w, h)
    if rad and " " in rad and rad.endswith("0"):      # a leaf: mirror its corners too
        left, right = f"{min(w, h)}px 0", f"0 {min(w, h)}px"
    else:
        left = right = rad
    els = [box(x, y, w, h, a, left), box(400 - x - w, y, w, h, a, right)]
    if R.random() < 0.6:
        cw, ch = snap(R, 20, 120), snap(R, 20, 200)
        els.insert(0 if R.random() < 0.5 else 2, box(200 - cw // 2, snap(R, 10, 290 - ch), cw, ch, b,
                                                      _shape_kind(R, cw, ch)))
    return page(bg, els)


def repeat(R, pal):
    bg, a, b = pal
    n = R.randint(2, 5)
    rows = 1 if R.random() < 0.6 else R.randint(2, 3)
    w, h = snap(R, 20, 300 // n - 10), snap(R, 20, 240 // rows - 10)
    dx = snap(R, w + 5, (380 - w) // max(1, n - 1)) if n > 1 else 0
    dy = snap(R, h + 5, (280 - h) // max(1, rows - 1)) if rows > 1 else 0
    x0 = snap(R, 10, max(10, 390 - w - dx * (n - 1)))
    y0 = snap(R, 10, max(10, 290 - h - dy * (rows - 1)))
    rad = _shape_kind(R, w, h)
    els = [box(x0 + i * dx, y0 + j * dy, w, h, a, rad) for j in range(rows) for i in range(n)]
    if R.random() < 0.4:
        els.insert(0, box(x0 - 10, y0 - 10, dx * (n - 1) + w + 20, dy * (rows - 1) + h + 20, b))
    return page(bg, els)


def rings(R, pal):
    bg, a, b = pal
    k = R.randint(3, 5)
    cx, cy = snap(R, 120, 280), snap(R, 100, 200)
    r0 = snap(R, 60, min(cx, 400 - cx, cy, 300 - cy, 140))
    step = max(10, snap(R, 10, r0 // k))
    rad = "50%" if R.random() < 0.7 else None
    cols = [a, b] if R.random() < 0.6 else [a, b, bg]
    els = []
    for i in range(k):
        r = r0 - i * step
        if r <= 0:
            break
        els.append(box(cx - r, cy - r, 2 * r, 2 * r, cols[i % len(cols)], rad))
    return page(bg, els)


def petals(R, pal):
    bg, a, b = pal
    n = R.choice([2, 3, 4, 6, 8])
    s = snap(R, 50, 100)
    cx, cy = 200, 150
    els = []
    d = s / math.sqrt(2)                  # half the leaf's diagonal: its tip sits at the center
    base = R.choice([0, 0, 45, 90])
    for i in range(n):
        ang = i * 360 // n + base
        # a square rounded on its top-left and bottom-right corners is a leaf
        # pointing along -45deg; turning it by ang + 45 points it along ang
        t = math.radians(ang)
        lx, ly = round(cx + d * math.cos(t) - s / 2), round(cy + d * math.sin(t) - s / 2)
        els.append(box(lx, ly, s, s, a, f"{s}px 0", rot=(ang + 45) % 360 or None))
    if R.random() < 0.7:
        c = snap(R, 20, 50)
        els.append(box(cx - c // 2, cy - c // 2, c, c, b, "50%"))
    return page(bg, els)


def stripes(R, pal):
    bg, a, b = pal
    n = R.randint(2, 5)
    vertical = R.random() < 0.5
    size = 400 if vertical else 300
    cuts = sorted(R.sample(range(1, size // 10), n - 1))
    edges = [0] + [10 * c for c in cuts] + [size]
    els = []
    for i in range(n):
        if i % 2 == 0:
            continue
        lo, hi = edges[i], edges[i + 1]
        els.append(box(lo, 0, hi - lo, 300, a) if vertical else box(0, lo, 400, hi - lo, a))
    if R.random() < 0.8:
        w = snap(R, 40, 140)
        els.append(box(200 - w // 2, 150 - w // 2, w, w, b, "50%" if R.random() < 0.6 else None,
                       rot=45 if R.random() < 0.2 else None))
    return page(bg, els)


def scatter(R, pal):
    bg, a, b = pal
    els = []
    for _ in range(R.randint(2, 5)):
        w, h = snap(R, 20, 200), snap(R, 20, 180)
        els.append(box(snap(R, 0, 400 - w), snap(R, 0, 300 - h), w, h, R.choice([a, b]), _shape_kind(R, w, h),
                       rot=R.choice([None, None, None, 15, 30, 45])))
    return page(bg, els)


GENERATORS = {f.__name__: f for f in (mirror, repeat, rings, petals, stripes, scatter)}


def generate(family, seed):
    R = random.Random(f"{family}:{seed}")
    while True:                # a draw whose sizes leave no room is redrawn
        pal = list(R.choice(PALETTES))
        R.shuffle(pal)
        try:
            return GENERATORS[family](R, tuple(pal))
        except ValueError:
            continue


def render(cases, out: Path):
    jobs = [{"html": c["code"], "out": str(out / f"{c['id']}.png")} for c in cases]
    (out / "jobs.json").write_text(json.dumps(jobs))
    subprocess.run(["node", str(BENCH / "render.js"), str(out / "jobs.json")], check=True, cwd=BENCH)
    (out / "jobs.json").unlink()


def build(out: Path, seeds, families=FAMILIES):
    out.mkdir(parents=True, exist_ok=True)
    cases = []
    for fam in families:
        for seed in seeds:
            code = generate(fam, seed)
            cid = f"{fam}-{seed}"
            (out / f"{cid}.html").write_text(code)
            cases.append({"id": cid, "family": fam, "code": code, "ref_len": len(code)})
    render(cases, out)
    (out / "cases.json").write_text(json.dumps([{k: v for k, v in c.items() if k != "code"} for c in cases],
                                               indent=1))
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("split", choices=["heldout", "heldout2", "heldout3", "train"])
    ap.add_argument("n", nargs="?", type=int, default=PER_FAMILY)
    ap.add_argument("--out")
    args = ap.parse_args()
    if args.split in HELDOUT_SEEDS:
        seeds = [HELDOUT_SEEDS[args.split] + i for i in range(PER_FAMILY)]
        out = Path(args.out or BENCH / args.split)
    else:
        seeds = list(range(args.n))      # never overlaps the held-out seeds
        out = Path(args.out or BENCH / "train")
    cases = build(out, seeds)
    print(f"wrote {len(cases)} targets to {out}")


if __name__ == "__main__":
    main()

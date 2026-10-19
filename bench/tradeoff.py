#!/usr/bin/env python3
"""Trace the characters-vs-match trade-off of the length-aware simplifier.

For each saved model in results.json and each rho, simplify, generate code,
render everything in Chromium and score it. Writes bench/tradeoff.json.

    python bench/tradeoff.py [--rhos 0,0.25,0.5,1,2,4]
"""

import argparse
import json
import statistics
import subprocess
import sys
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cssynth.codegen import emit  # noqa: E402
from cssynth.search import extract_palette  # noqa: E402
from cssynth.shapes import Shape, bg_from_json  # noqa: E402
from cssynth.simplify import simplify  # noqa: E402

BENCH = ROOT / "bench"
OUT = BENCH / "tradeoff"


def load(r):
    m = r["model"]
    shapes = [Shape(**{**s, "radii": tuple(s["radii"]),
                       "poly": tuple(map(tuple, s["poly"])) if s["poly"] else None})
              for s in m["shapes"]]
    return np.array(m["palette"]), bg_from_json(m["bg"]), shapes


def work(args):
    r, rhos = args
    pal, bg, shapes = load(r)
    img = np.asarray(Image.open(BENCH / "human" / f"{r['id']}.png").convert("RGB"))
    _, T = extract_palette(img)
    rows = []
    for rho in rhos:
        out = shapes if rho == 0 else simplify(T, bg, pal, shapes, rho=rho)
        code, info = emit(pal, bg, out)
        rows.append({"id": r["id"], "rho": rho, "chars": len(code), "code": code,
                     "shapes": len(out)})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rhos", default="0,0.25,0.5,1,2,4")
    args = ap.parse_args()
    rhos = [float(x) for x in args.rhos.split(",")]
    res = json.loads((BENCH / "results.json").read_text())
    OUT.mkdir(exist_ok=True)
    with Pool() as p:
        rows = [row for rs in p.map(work, [(r, rhos) for r in res]) for row in rs]
    jobs = []
    for row in rows:
        row["png"] = f"bench/tradeoff/{row['id']}__{row['rho']}.png"     # relative to the repo
        jobs.append({"html": row["code"], "out": str(ROOT / row["png"])})
    (BENCH / "jobs_tradeoff.json").write_text(json.dumps(jobs))
    subprocess.run(["node", str(BENCH / "render.js"), str(BENCH / "jobs_tradeoff.json")],
                   check=True, cwd=BENCH)
    for row in rows:
        tgt = np.asarray(Image.open(BENCH / "human" / f"{row['id']}.png").convert("RGB")).astype(int)
        got = np.asarray(Image.open(ROOT / row["png"]).convert("RGB")).astype(int)
        row["match"] = round(float((np.abs(got - tgt).max(2) <= 8).mean() * 100), 2)
    (BENCH / "tradeoff.json").write_text(json.dumps(rows, indent=1))
    print(f"{'rho':>5} {'>=99%':>6} {'>=99.5%':>8} {'median chars':>13} {'total chars':>12} {'median match':>13}")
    for rho in rhos:
        rs = [x for x in rows if x["rho"] == rho]
        print(f"{rho:5g} {sum(x['match'] >= 99 for x in rs):6d} {sum(x['match'] >= 99.5 for x in rs):8d} "
              f"{statistics.median(x['chars'] for x in rs):13.0f} {sum(x['chars'] for x in rs):12d} "
              f"{statistics.median(x['match'] for x in rs):13.2f}")


if __name__ == "__main__":
    main()

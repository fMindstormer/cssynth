#!/usr/bin/env python3
"""Compile every target, render the output in Chromium, and score it.

    python bench/run.py [--only id,id] [--jobs 8]

Writes bench/out/<id>.html, bench/out/<id>.png and bench/results.json.
Match = share of pixels whose largest channel difference is at most 8/255,
measured on Chromium's own render of our code against Chromium's render of
the human solution.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cssynth.compiler import compile_image  # noqa: E402
from cssynth.shapes import bg_to_json, render_rgb  # noqa: E402

BENCH = ROOT / "bench"
OUT = BENCH / "out"


def match(a, b, tol=8):
    return float((np.abs(a.astype(int) - b.astype(int)).max(2) <= tol).mean() * 100)


def work(case):
    t = time.time()
    target = BENCH / "human" / f"{case['id']}.png"
    code, info, (pal, bg, T, shapes) = compile_image(target)
    sim = render_rgb(bg, pal, shapes)
    img = np.asarray(Image.open(target).convert("RGB"))
    (OUT / f"{case['id']}.html").write_text(code)
    from dataclasses import asdict
    return {"id": case["id"], "chars": len(code), "code": code, **info,
            "model": {"palette": pal.tolist(), "bg": bg_to_json(bg), "shapes": [asdict(s) for s in shapes]},
            "colors": int(len(pal)), "sim_match": match(sim, img),
            "seconds": round(time.time() - t, 1)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    args = ap.parse_args()
    cases = json.loads((BENCH / "cases.json").read_text())
    if args.only:
        keep = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in keep]
    OUT.mkdir(exist_ok=True)
    with Pool(args.jobs) as p:
        res = p.map(work, cases)

    jobs = [{"html": r["code"], "out": str(OUT / f"{r['id']}.png")} for r in res]
    (BENCH / "jobs_out.json").write_text(json.dumps(jobs))
    subprocess.run(["node", str(BENCH / "render.js"), str(BENCH / "jobs_out.json")], check=True, cwd=BENCH)

    by_id = {c["id"]: c for c in cases}
    for r in res:
        c = by_id[r["id"]]
        tgt = np.asarray(Image.open(BENCH / "human" / f"{r['id']}.png").convert("RGB"))
        got = np.asarray(Image.open(OUT / f"{r['id']}.png").convert("RGB"))
        r["match"] = round(match(got, tgt), 2)
        r["exact"] = round(match(got, tgt, 0), 2)
        r["human_len"], r["human_min_len"] = c["human_len"], c["human_min_len"]
        r["title"], r["source"] = c["title"], c["source"]
    old = {}
    rp = BENCH / "results.json"
    if rp.exists() and args.only:
        old = {r["id"]: r for r in json.loads(rp.read_text())}
    old.update({r["id"]: r for r in res})
    allres = [old[c["id"]] for c in json.loads((BENCH / "cases.json").read_text()) if c["id"] in old]
    rp.write_text(json.dumps(allres, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))

    for r in res:
        print(f"{r['id']:28s} match {r['match']:6.2f}%  (sim {r['sim_match']:6.2f})  "
              f"{r['chars']:4d} chars vs human {r['human_min_len']:4d} min  "
              f"{r['shapes']:2d} shapes {r['shadows']} shadows  {r['seconds']}s")
    ok = [r for r in res if r["match"] >= 99]
    print(f"\n{len(ok)}/{len(res)} at >=99% match; "
          f"median chars ours {np.median([r['chars'] for r in ok]):.0f} vs human-minified "
          f"{np.median([r['human_min_len'] for r in ok]):.0f} on those")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Ablation study: what each technique contributes.

Each configuration switches off one part of the compiler and recompiles all
66 targets. Scores use cssynth's own rasterizer (no Chromium), so they are
comparable with each other, not with the rendered benchmark.

    python bench/ablation.py --config no-research    # writes bench/ablation/no-research.json
    python bench/ablation.py --table                 # combines them: bench/ablation.json, a table
"""

import argparse
import json
import os
import sys
import time
from multiprocessing import Pool
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cssynth import codegen, compiler, improve, search  # noqa: E402

BENCH = ROOT / "bench"
OUT = BENCH / "ablation"


def _regions_8(region, lab, objs):
    """search._regions without splitting regions that touch at corners."""
    for idx, sl in objs:
        ys, xs = sl
        if (ys.stop - ys.start) * (xs.stop - xs.start) >= 16:
            yield lab[sl] == idx, xs, ys


def _no_simplify(T, bg, pal, shapes, **kw):
    return shapes


# name: (what is switched off, how)
ABLATIONS = {
    "full": ("nothing", lambda: None),
    "no-research": ("re-search of the best result", None),
    "no-cleanup": ("length-aware clean-up", lambda: (setattr(compiler, "simplify", _no_simplify),
                                                     setattr(improve, "simplify", _no_simplify))),
    "no-exact-grouping": ("exact (CP-SAT) shadow grouping; greedy only",
                          lambda: setattr(codegen, "make_groups_exact", lambda *a, **k: None)),
    "no-box-shadows": ("box-shadows", lambda: setattr(codegen, "shadow_of", lambda a, b: None)),
    "no-tag-rules": ("per-tag rules (<i>, <u>, <s>)",
                     lambda: setattr(codegen, "tag_options", lambda els: iter([None]))),
    "no-clip-reuse": ("clip-path reuse for copies and mirrors",
                      lambda: setattr(codegen, "reused_clip", lambda a, b: None)),
    "top-only": ("insertion at any depth; new shapes go on top",
                 lambda: setattr(search, "INSERT_ANYWHERE", False)),
    "no-corner-split": ("splitting regions that touch at corners", lambda: setattr(search, "_regions", _regions_8)),
    "no-outline-polygons": ("polygons traced from outlines", None),
    "no-length-aware": ("length-aware shape choice; by pixels only", None),
    "no-gradient-base": ("gradient backgrounds", None),
    "no-soft-stops": ("soft gradient stops", lambda: setattr(search, "soften", lambda g, img, pal: g)),
    "no-motifs": ("nested-ring motifs", lambda: setattr(search, "MOTIFS", set())),
}


def variants(name):
    v = compiler.VARIANTS
    if name == "no-outline-polygons":
        v = [x for x in v if not x[4]]
    if name == "no-gradient-base":
        v = [x for x in v if x[3] != "gradient"]
    if name == "no-length-aware":
        v = [x for x in v if not x[5]]
    return v


def setup(name):
    patch = ABLATIONS[name][1]
    if patch:
        patch()


def work(args):
    name, case = args
    t = time.time()
    code, info, _ = compiler.compile_image(BENCH / "human" / f"{case['id']}.png", variants=variants(name),
                                           research=name != "no-research")
    return {"id": case["id"], "chars": len(code), "wrong_px": info["wrong_px"], "J": info["J"],
            "human_min_len": case["human_min_len"], "seconds": round(time.time() - t, 1)}


def run(name, jobs, only=None):
    cases = json.loads((BENCH / "cases.json").read_text())
    if only:
        cases = [c for c in cases if c["id"] in only.split(",")]
    with Pool(jobs, initializer=setup, initargs=(name,)) as p:
        rows = p.map(work, [(name, c) for c in cases], chunksize=1)
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(rows, indent=1))
    print(f"{name}: {sum(r['chars'] for r in rows)} chars, J {sum(r['J'] for r in rows):.0f}")


def table():
    rows = []
    for name, (what, _) in ABLATIONS.items():
        p = OUT / f"{name}.json"
        if not p.exists():
            continue
        rs = json.loads(p.read_text())
        rows.append({"config": name, "off": what, "chars": sum(r["chars"] for r in rs),
                     "J": round(sum(r["J"] for r in rs)), "shorter": sum(r["chars"] < r["human_min_len"] for r in rs),
                     "cpu_min": round(sum(r["seconds"] for r in rs) / 60, 1), "n": len(rs)})
    (BENCH / "ablation.json").write_text(json.dumps(rows, indent=1))
    full = next(r for r in rows if r["config"] == "full")
    print("| Switched off | Total J | Characters | Shorter than human | CPU min |")
    print("|---|---|---|---|---|")
    for r in rows:
        dj = "" if r is full else f" ({(r['J'] / full['J'] - 1) * 100:+.1f}%)"
        dc = "" if r is full else f" ({r['chars'] - full['chars']:+,})"
        print(f"| {r['off']} | {r['J']:,}{dj} | {r['chars']:,}{dc} | {r['shorter']} / {r['n']} | {r['cpu_min']} |")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", choices=ABLATIONS)
    ap.add_argument("--table", action="store_true")
    ap.add_argument("--jobs", type=int, default=os.cpu_count())
    ap.add_argument("--only", help="comma-separated case ids (for a quick check)")
    args = ap.parse_args()
    if args.config:
        run(args.config, args.jobs, args.only)
    if args.table:
        table()


if __name__ == "__main__":
    main()

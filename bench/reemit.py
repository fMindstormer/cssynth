#!/usr/bin/env python3
"""Re-run only code generation on the shapes saved in results.json, render
the new code in Chromium and re-score. Use after changing cssynth/codegen.py."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from cssynth.codegen import emit  # noqa: E402
from cssynth.shapes import Shape, bg_from_json  # noqa: E402

BENCH = ROOT / "bench"
OUT = BENCH / "out"


def main():
    rp = BENCH / "results.json"
    res = json.loads(rp.read_text())
    jobs = []
    for r in res:
        m = r["model"]
        shapes = [Shape(**{**s, "radii": tuple(s["radii"]),
                           "poly": tuple(map(tuple, s["poly"])) if s["poly"] else None})
                  for s in m["shapes"]]
        code, info = emit(np.array(m["palette"]), bg_from_json(m["bg"]), shapes)
        r["code"], r["chars"] = code, len(code)
        r.update({k: v for k, v in info.items()})
        (OUT / f"{r['id']}.html").write_text(code)
        jobs.append({"html": code, "out": str(OUT / f"{r['id']}.png")})
    (BENCH / "jobs_out.json").write_text(json.dumps(jobs))
    subprocess.run(["node", str(BENCH / "render.js"), str(BENCH / "jobs_out.json")], check=True, cwd=BENCH)
    for r in res:
        tgt = np.asarray(Image.open(BENCH / "human" / f"{r['id']}.png").convert("RGB")).astype(int)
        got = np.asarray(Image.open(OUT / f"{r['id']}.png").convert("RGB")).astype(int)
        r["match"] = round(float((np.abs(got - tgt).max(2) <= 8).mean() * 100), 2)
        r["exact"] = round(float((np.abs(got - tgt).max(2) == 0).mean() * 100), 2)
    rp.write_text(json.dumps(res, indent=1))
    ok = [r for r in res if r["match"] >= 99]
    print(f"{len(ok)}/{len(res)} at >=99%; median chars {np.median([r['chars'] for r in ok]):.0f} "
          f"vs human-minified {np.median([r['human_min_len'] for r in ok]):.0f}")


if __name__ == "__main__":
    main()

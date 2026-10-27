"""Precompute the saved results the in-browser demo shows before Python has
loaded: examples/saved.json.

    CHROME_PATH=... python save_examples.py

Each example is compiled with the page's default settings by common.py, so
"Compile again" in the browser starts from the same settings. The code is
also rendered in Chromium (bench/render.js) and compared with the target, so
the page can show a real browser measurement next to the internal estimate.
"""

import json
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from common import compile_picture  # noqa: E402

EXAMPLES = [
    ("om-20240318.png", "Clean success", "A dark red arch with a stepped notch",
     "One clip-path polygon draws the whole arch."),
    ("om-20240224.png", "Reuse", "A keyboard with rounded keys",
     "Each row of keys is one element repeated with box-shadows."),
    ("om-20240301.png", "Limitation", "A star of rotated wedges around a circle",
     "Rotated wedges and a polygon for the circle: long code, with visible facets and edge errors."),
]


def chromium_version():
    out = subprocess.run(["node", "-e", "const p=require('puppeteer-core');p.launch({executablePath:"
                          "process.env.CHROME_PATH,args:['--disable-gpu']}).then(async b=>{"
                          "console.log(await b.version());await b.close()})"],
                         capture_output=True, text=True, check=True, cwd=HERE.parent / "bench")
    return out.stdout.strip()


def main():
    saved = []
    with tempfile.TemporaryDirectory() as tmp:
        jobs = []
        for file, kind, label, what in EXAMPLES:
            r = compile_picture(Image.open(HERE / "examples" / file))
            saved.append({"file": file, "kind": kind, "label": label, "what": what, **r})
            jobs.append({"html": r["code"], "out": str(Path(tmp) / file)})
        (Path(tmp) / "jobs.json").write_text(json.dumps(jobs))
        bench = HERE.parent / "bench"
        subprocess.run(["node", str(bench / "render.js"), str(Path(tmp) / "jobs.json")], check=True, cwd=bench)
        for s, job in zip(saved, jobs):
            target = np.asarray(Image.open(HERE / "examples" / s["file"]).convert("RGB")).astype(int)
            got = np.asarray(Image.open(job["out"]).convert("RGB")).astype(int)
            s["chromium_match"] = round(float((np.abs(got - target).max(2) <= 8).mean() * 100), 2)
            print(s["file"], s["chars"], "chars, estimate", s["estimated_match"], "Chromium", s["chromium_match"])
    version = re.search(r'^version = "(.+)"', (HERE.parent / "pyproject.toml").read_text(), re.M)[1]
    out = {"cssynth": version,
           "chromium": f"{chromium_version()} on {platform.system().replace('Darwin', 'macOS')}", "examples": saved}
    (HERE / "examples" / "saved.json").write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()

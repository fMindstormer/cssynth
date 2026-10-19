#!/usr/bin/env python3
"""Collect CSSBattle targets and human solutions from the vendored repos.

Writes bench/cases.json: [{id, title, source, license, human_code, human_len,
human_min_len, official_png}]. Human code is rendered later (render.js) to
produce the exact target image.

Only MIT-licensed solutions (OmPreetham/cssbattle) keep their code in
cases.json. Kushalshakya/CSSBattle has no license, so its entries carry only
metadata; bench/fetch.py downloads that code at a pinned commit and renders
the targets locally.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"

KS_REPO, KS_COMMIT = "Kushalshakya/CSSBattle", "8972f4aec818e0f5a1657160bb2c8f250be98359"
OM_REPO, OM_COMMIT = "OmPreetham/cssbattle", "5a0dda2882fbd920dcc774b541b857e754e6f5a4"


def minify(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    code = re.sub(r"<!--.*?-->", "", code, flags=re.S)
    code = re.sub(r"\s+", " ", code)
    code = re.sub(r"\s*([{}:;,>])\s*", r"\1", code)
    code = code.replace(";}", "}")
    return code.strip()


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def kushalshakya_cases(repo: Path):
    """Each solution is one .css file whose leading comment holds the HTML."""
    cases = []
    for f in sorted(repo.glob("Battle */*.css")):
        text = f.read_text(errors="replace")
        m = re.match(r"\s*/\*(.*?)\*/(.*)", text, flags=re.S)
        if not m:
            continue
        html, css = m.group(1).strip(), m.group(2).strip()
        code = f"{html}\n<style>\n{css}\n</style>"
        num, _, title = f.stem.partition("-")
        cases.append({
            "id": f"ks-{num}-{slug(title)}",
            "title": re.sub(r"(?<=[a-z])(?=[A-Z])", " ", title),
            "source": f"{KS_REPO}: {f.parent.name}/{f.name}",
            "license": None,
            "human_code": code,
            "official_png": None,
        })
    return cases


def ompreetham_cases(repo: Path):
    cases = []
    for d in sorted((repo / "daily-targets").glob("*/*/*")):
        idx, png = d / "index.html", d / "screenshots" / "css-image.png"
        if not idx.exists():
            continue
        y, mo, da = d.parts[-3:]
        cases.append({
            "id": f"om-{y}{mo}{da}",
            "title": f"Daily target {y}-{mo}-{da}",
            "source": f"{OM_REPO}: daily-targets/{y}/{mo}/{da}",
            "license": "MIT",
            "human_code": idx.read_text(errors="replace").strip(),
            "official_png": str(png.relative_to(ROOT)) if png.exists() else None,
        })
    return cases


def main():
    cases = (kushalshakya_cases(VENDOR / "Kushalshakya_CSSBattle")
             + ompreetham_cases(VENDOR / "OmPreetham_cssbattle"))
    for c in cases:
        c["human_len"] = len(c["human_code"])
        c["human_min_len"] = len(minify(c["human_code"]))
        if not c["license"]:
            del c["human_code"]
    out = ROOT / "bench" / "cases.json"
    out.write_text(json.dumps(cases, indent=1))
    print(f"{len(cases)} cases -> {out}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Build the write-up page: fill docs/blog/index.html with numbers and code
from bench/results.json and bench/ablation.json, and copy the images it shows.

    python bench/build_blog.py site/blog     # -> site/blog/index.html, site/blog/img/

Only targets from licensed solutions are shown (see THIRD_PARTY.md)."""

import json
import re
import shutil
import sys
from html import escape
from pathlib import Path

from build_page import ablation_table, fmt

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "bench"


def main():
    out = Path(sys.argv[1])
    page = (ROOT / "docs" / "blog" / "index.html").read_text()
    res = {r["id"]: r for r in json.loads((BENCH / "results.json").read_text())}
    licensed = {c["id"] for c in json.loads((BENCH / "cases.json").read_text()) if c.get("license")}
    abl = {r["config"]: r for r in json.loads((BENCH / "ablation.json").read_text())}
    full = abl["full"]
    rows = list(res.values())
    stats = {
        "n": len(rows),
        "shorter": sum(r["chars"] < r["human_min_len"] for r in rows),
        "ok": sum(r["match"] >= 99 for r in rows),
        "total": fmt(sum(r["chars"] for r in rows)),
        "human_total": fmt(sum(r["human_min_len"] for r in rows)),
        "length_wins": sum(bool(r["variant"][5]) for r in rows),
        "length_chars": fmt(abl["no-length-aware"]["chars"] - full["chars"]),
        "ABLATION": ablation_table(),
    }
    for k, v in stats.items():
        page = page.replace("{{" + k + "}}", str(v))
    page = re.sub(r"\{\{abl:([\w-]+)\}\}", lambda m: f"{(abl[m[1]]['J'] / full['J'] - 1) * 100:.1f}%", page)

    shown = set(re.findall(r"img/([\w-]+)-[to]\.png", page))
    assert shown <= licensed, shown - licensed
    fields = {"code": lambda r: escape(r["code"]), "chars": lambda r: r["chars"],
              "human": lambda r: r["human_min_len"], "match": lambda r: f"{r['match']:.2f}".rstrip("0").rstrip(".")}
    page = re.sub(r"\{\{(code|chars|human|match):([\w-]+)\}\}", lambda m: str(fields[m[1]](res[m[2]])), page)
    assert "{{" not in page, re.findall(r"\{\{[^}]*\}\}", page)

    (out / "img").mkdir(parents=True, exist_ok=True)
    for cid in shown:
        shutil.copy(BENCH / "human" / f"{cid}.png", out / "img" / f"{cid}-t.png")
        shutil.copy(BENCH / "out" / f"{cid}.png", out / "img" / f"{cid}-o.png")
    (out / "index.html").write_text(page)
    print(f"wrote {out / 'index.html'} with {len(shown)} examples")


if __name__ == "__main__":
    main()

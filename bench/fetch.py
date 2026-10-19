#!/usr/bin/env python3
"""Download the benchmark targets that cannot be redistributed, and render them.

    python bench/fetch.py [--force]

Kushalshakya/CSSBattle has no license, so its solutions are not part of this
repository. This downloads that repo at the pinned commit into vendor/,
checks every solution against the lengths recorded in bench/cases.json, and
renders the missing targets to bench/human/<id>.png with render.js.
"""

import argparse
import json
import subprocess
import sys

from prepare import KS_COMMIT, KS_REPO, ROOT, VENDOR, kushalshakya_cases, minify

BENCH = ROOT / "bench"


def download(repo: str, commit: str, dest):
    """Shallow-clone repo at exactly this commit."""
    if (dest / ".git").exists():
        return
    print(f"downloading {repo} at {commit[:7]}")
    dest.mkdir(parents=True, exist_ok=True)
    for cmd in (["init", "-q"], ["fetch", "-q", "--depth", "1", f"https://github.com/{repo}.git", commit],
                ["-c", "advice.detachedHead=false", "checkout", "-q", "FETCH_HEAD"]):
        subprocess.run(["git", *cmd], check=True, cwd=dest)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--force", action="store_true", help="re-render targets that already exist")
    args = ap.parse_args()
    repo = VENDOR / "Kushalshakya_CSSBattle"
    download(KS_REPO, KS_COMMIT, repo)
    fetched = {c["id"]: c for c in kushalshakya_cases(repo)}
    cases = [c for c in json.loads((BENCH / "cases.json").read_text()) if not c.get("license")]
    jobs = []
    for c in cases:
        f = fetched.get(c["id"])
        if f is None or (len(f["human_code"]), len(minify(f["human_code"]))) != (c["human_len"], c["human_min_len"]):
            sys.exit(f"{c['id']}: downloaded solution does not match bench/cases.json")
        out = BENCH / "human" / f"{c['id']}.png"
        if args.force or not out.exists():
            jobs.append({"html": f["human_code"], "out": str(out)})
    print(f"{len(cases)} solutions verified; rendering {len(jobs)} targets")
    if jobs:
        (BENCH / "jobs_fetch.json").write_text(json.dumps(jobs))
        subprocess.run(["node", str(BENCH / "render.js"), str(BENCH / "jobs_fetch.json")], check=True, cwd=BENCH)


if __name__ == "__main__":
    main()

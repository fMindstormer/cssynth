#!/usr/bin/env python3
"""Frontier language models on the same targets: can't an LLM just do this?

    python bench/llm.py --set tiny --model anthropic:claude-opus-5-5 --only 0,1,2
    python bench/llm.py --set heldout3 --model openai:gpt-6-astra --rounds 4
    python bench/llm.py --set tiny --model cssynth          # cssynth's results, for the table
    python bench/llm.py --set tiny --compare cssynth anthropic:claude-opus-5-5 openai:gpt-6-astra

Each model plays CSSBattle the way a person does: it sees the target image
and its colors, writes code, and gets its render back with the score, for a
few rounds. The best solved answer counts (the shortest at >= 99% match, or
else the closest). Outputs are rendered by the same Chromium as everything
else (render.js, JavaScript off) and scored with evaluate.match.

Keys come from the environment (ANTHROPIC_API_KEY, OPENAI_API_KEY,
GEMINI_API_KEY) or, for those not set there, from KEY=value lines in
~/.config/cssynth/keys.env. Model ids are given as provider:model. Results go to
bench/eval/llm-<set>-<model>.json, with the tokens each call used.

Sets: "tiny" (the known-optimum targets of tiny.py, rendered from their
optimal code), "dev", "train" and the held-out sets, as in evaluate.py.
"""

import argparse
import base64
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench"))
from evaluate import FIDELITY, match, targets  # noqa: E402

BENCH = ROOT / "bench"
EVAL = BENCH / "eval"

RULES = """You are playing CSSBattle. Write HTML/CSS that renders exactly like the target image.

How your code is judged:
- It is placed as-is into an empty page (no doctype, so quirks mode) and rendered by
  Chromium in a 400x300 px frame, with the browser's default styles (for example, body
  has an 8px margin).
- A pixel matches when each of its color channels is within 8 of the target's. Your code
  must match at least 99% of the pixels.
- Among matching answers, fewer characters is better. Every character counts, including
  whitespace. Anything that renders is allowed: omitted closing tags, unquoted attributes,
  short color forms. No JavaScript, no external resources.

The target's colors, by share of pixels: {colors}.

You have {rounds} attempts. After each one you will see what your code rendered, a map of
the wrong pixels, its match and its length. Reply with your code in a single ```html block."""

FEEDBACK = ("Your code is {chars} characters and matches {match:.2f}% of pixels ({verdict}). "
            "First image: what it rendered. Second image: the wrong pixels in red. {ask} "
            "Attempts left: {left}. Reply with your code in a single ```html block.")


def png_b64(arr):
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def palette_text(arr):
    counts = Counter(map(tuple, arr.reshape(-1, 3)))
    total = arr.shape[0] * arr.shape[1]
    top = [(c, n) for c, n in counts.most_common() if n / total >= 0.001][:12]
    return ", ".join(f"#{c[0]:02x}{c[1]:02x}{c[2]:02x} ({100 * n / total:.1f}%)" for c, n in top)


def extract(text):
    blocks = re.findall(r"```(?:html|HTML)?[ \t]*\n(.*?)```", text, re.S)
    code = blocks[-1] if blocks else text
    return code.strip("\n")


KEYS = Path.home() / ".config" / "cssynth" / "keys.env"


def load_keys():
    if KEYS.exists():
        for line in KEYS.read_text().splitlines():
            k, sep, v = line.strip().removeprefix("export ").partition("=")
            if sep and not k.startswith("#"):
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


# Messages are [(role, [str | ("image", b64)])], turned into each provider's format.

def _post(url, headers, body, tries=6):
    data = json.dumps(body).encode()
    for i in range(tries):
        req = urllib.request.Request(url, data=data, headers={"content-type": "application/json", **headers})
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode(errors="replace")[:500]
            if e.code in (429, 500, 502, 503, 504, 529) and i < tries - 1:
                time.sleep(min(120, 5 * 2 ** i))
                continue
            raise RuntimeError(f"HTTP {e.code}: {msg}") from None
        except (urllib.error.URLError, TimeoutError):
            if i == tries - 1:
                raise
            time.sleep(min(120, 5 * 2 ** i))


def anthropic(model, messages, effort):
    msgs = [{"role": role, "content": [{"type": "text", "text": p} if isinstance(p, str) else
                                       {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                                    "data": p[1]}} for p in parts]}
            for role, parts in messages]
    body = {"model": model, "max_tokens": 32000, "messages": msgs}       # thinking is on by default
    if effort:
        body["output_config"] = {"effort": effort}
    r = _post("https://api.anthropic.com/v1/messages",
              {"x-api-key": os.environ["ANTHROPIC_API_KEY"], "anthropic-version": "2023-06-01"}, body)
    text = "".join(b.get("text", "") for b in r["content"] if b["type"] == "text")
    u = r["usage"]
    return text, {"in": u["input_tokens"] + u.get("cache_creation_input_tokens", 0)
                  + u.get("cache_read_input_tokens", 0), "out": u["output_tokens"]}


def openai(model, messages, effort):
    msgs = [{"role": role, "content": [{"type": "input_text" if role == "user" else "output_text", "text": p}
                                       if isinstance(p, str) else
                                       {"type": "input_image", "image_url": f"data:image/png;base64,{p[1]}"}
                                       for p in parts]}
            for role, parts in messages]
    body = {"model": model, "input": msgs, "max_output_tokens": 32000}
    if effort:
        body["reasoning"] = {"effort": effort}
    r = _post("https://api.openai.com/v1/responses", {"authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"}, body)
    text = "".join(c.get("text", "") for o in r["output"] if o["type"] == "message" for c in o["content"])
    u = r["usage"]
    return text, {"in": u["input_tokens"], "out": u["output_tokens"]}


def gemini(model, messages, effort):
    contents = [{"role": "model" if role == "assistant" else "user",
                 "parts": [{"text": p} if isinstance(p, str) else
                           {"inline_data": {"mime_type": "image/png", "data": p[1]}} for p in parts]}
                for role, parts in messages]
    body = {"contents": contents, "generationConfig": {"maxOutputTokens": 32000}}
    if effort:
        body["generationConfig"]["thinkingConfig"] = {"thinkingLevel": effort.upper()}
    r = _post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
              {"x-goog-api-key": os.environ["GEMINI_API_KEY"]}, body)
    parts = r["candidates"][0].get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    u = r.get("usageMetadata", {})
    return text, {"in": u.get("promptTokenCount", 0),
                  "out": u.get("candidatesTokenCount", 0) + u.get("thoughtsTokenCount", 0)}


def dummy(model, messages, effort):
    """No API: answers a white box, to test the loop."""
    return '```html\n<p style="background:#fff;margin:50">\n```', {"in": 0, "out": 0}


PROVIDERS = {"anthropic": anthropic, "openai": openai, "gemini": gemini, "dummy": dummy}


def render(codes):
    """[html] -> [array or None], in Chromium with JavaScript off."""
    with tempfile.TemporaryDirectory() as d:
        jobs = [{"html": c, "out": f"{d}/{i}.png"} for i, c in enumerate(codes)]
        Path(d, "jobs.json").write_text(json.dumps(jobs))
        subprocess.run(["node", str(BENCH / "render.js"), f"{d}/jobs.json"], check=True, cwd=BENCH,
                       capture_output=True, env={**os.environ, "NO_JS": "1"})
        return [np.asarray(Image.open(j["out"]).convert("RGB")) if Path(j["out"]).exists() else None
                for j in jobs]


def tiny_targets():
    """The known-optimum targets, rendered from their optimal code."""
    d = BENCH / "eval" / "tiny-targets"
    d.mkdir(parents=True, exist_ok=True)
    cases = json.loads((BENCH / "tiny.json").read_text())
    missing = [c for c in cases if not (d / f"{c['seed']}.png").exists()]
    if missing:
        for c, img in zip(missing, render([c["optimal_code"] for c in missing])):
            Image.fromarray(img).save(d / f"{c['seed']}.png")
    return [(str(c["seed"]), "tiny", d / f"{c['seed']}.png", c["optimal"]) for c in cases]


def play(provider, model, effort, rounds, target):
    cid, fam, path, ref = target
    T = np.asarray(Image.open(path).convert("RGB"))
    messages = [("user", [("image", png_b64(T)), RULES.format(colors=palette_text(T), rounds=rounds)])]
    tries, usage = [], {"in": 0, "out": 0}
    t = time.time()
    for k in range(rounds):
        try:
            text, u = PROVIDERS[provider](model, messages, effort)
        except Exception as e:                # keep what we have
            tries.append({"error": str(e)[:300]})
            break
        usage = {key: usage[key] + u[key] for key in usage}
        code = extract(text)
        img = render([code])[0]
        m = round(match(img, T), 2) if img is not None else 0.0
        tries.append({"chars": len(code), "match": m, "code": code})
        if k == rounds - 1:
            break
        ok = m >= FIDELITY
        wrong = np.zeros_like(T) + 255
        if img is not None:
            wrong[np.abs(img.astype(int) - T.astype(int)).max(2) > 8] = (255, 0, 0)
        ask = ("Make it shorter while keeping at least 99%." if ok
               else "Fix it to reach at least 99%, then make it short.")
        messages += [("assistant", [f"```html\n{code}\n```"]),
                     ("user", [("image", png_b64(img if img is not None else np.zeros_like(T))),
                               ("image", png_b64(wrong)),
                               FEEDBACK.format(chars=len(code), match=m, verdict="solved" if ok else "not yet",
                                               ask=ask, left=rounds - k - 1)])]
    ok = [x for x in tries if x.get("match", 0) >= FIDELITY]
    best = min(ok, key=lambda x: x["chars"]) if ok else max(tries, key=lambda x: x.get("match", 0))
    return {"id": cid, "family": fam, "ref_len": ref, "chars": best.get("chars", 0), "match": best.get("match", 0),
            "code": best.get("code", ""), "tries": tries, "tokens": usage, "seconds": round(time.time() - t, 1)}


def save_cssynth(set_name, tg):
    """cssynth's own results in the same format: tiny.py's outputs rendered
    here, or a saved evaluate.py run of the default compiler."""
    if set_name == "tiny":
        cases = {str(c["seed"]): c for c in json.loads((BENCH / "tiny.json").read_text())}
        codes = [cases[t[0]]["cssynth_code"] for t in tg]
        res = [{"id": t[0], "family": t[1], "ref_len": t[3], "chars": len(c), "code": c,
                "match": round(match(img, np.asarray(Image.open(t[2]).convert("RGB"))), 2),
                "tokens": {"in": 0, "out": 0}} for t, c, img in zip(tg, codes, render(codes))]
    else:
        res = [{**r, "tokens": {"in": 0, "out": 0}} for r in json.loads((EVAL / f"{set_name}-full.json").read_text())]
    (EVAL / f"llm-{set_name}-cssynth.json").write_text(json.dumps(res, indent=1))
    summarize(set_name, ["cssynth"])


def slug(model):
    return model.replace(":", "-").replace("/", "-")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="tiny")
    ap.add_argument("--model", help="provider:model, e.g. anthropic:claude-opus-5-5")
    ap.add_argument("--effort", help="reasoning effort, passed to the provider (e.g. low, medium, high)")
    ap.add_argument("--rounds", type=int, default=4)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--only")
    ap.add_argument("--compare", nargs="+", metavar="MODEL")
    args = ap.parse_args()
    if args.compare:
        summarize(args.set, args.compare)
        return
    tg = tiny_targets() if args.set == "tiny" else targets(args.set)
    if args.model == "cssynth":
        save_cssynth(args.set, tg)
        return
    load_keys()
    provider, model = args.model.split(":", 1)
    if args.only:
        keep = set(args.only.split(","))
        tg = [t for i, t in enumerate(tg) if t[0] in keep or str(i) in keep]
    out = EVAL / f"llm-{args.set}-{slug(args.model)}{'-' + args.effort if args.effort else ''}.json"
    done = {r["id"]: r for r in json.loads(out.read_text())} if out.exists() else {}
    todo = [t for t in tg if t[0] not in done or "error" in done[t[0]]["tries"][-1]]
    with ThreadPoolExecutor(args.jobs) as ex:
        for r in ex.map(lambda t: play(provider, model, args.effort, args.rounds, t), todo):
            done[r["id"]] = r
            out.write_text(json.dumps(list(done.values()), indent=1))
            print(f"{r['id']:16s} {r['chars']:5d} ch {r['match']:6.2f}%  (reference {r['ref_len']})  "
                  f"{r['tokens']['in']}+{r['tokens']['out']} tokens  {r['seconds']} s", flush=True)
    summarize(args.set, [args.model + (f"-{args.effort}" if args.effort else "")])


def summarize(set_name, models):
    runs = {m: {r["id"]: r for r in json.loads((EVAL / f"llm-{set_name}-{slug(m)}.json").read_text())}
            for m in models}
    ids = sorted(set.intersection(*(set(r) for r in runs.values())))
    common = [i for i in ids if all(runs[m][i]["match"] >= FIDELITY for m in models)]
    ref = next(iter(runs.values()))
    print(f"{len(ids)} targets; lengths on the {len(common)} all solve "
          f"(reference {sum(ref[i]['ref_len'] for i in common)} characters)")
    for m, rs in runs.items():
        solved = sum(rs[i]["match"] >= FIDELITY for i in ids)
        tok = sum(rs[i]["tokens"]["in"] + rs[i]["tokens"]["out"] for i in ids)
        print(f"  {m:40s} {solved:3d}/{len(ids)} solved  {sum(rs[i]['chars'] for i in common):7d} ch  "
              f"{tok:9d} tokens")


if __name__ == "__main__":
    main()

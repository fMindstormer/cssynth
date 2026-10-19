#!/usr/bin/env python3
"""Build the self-contained results page from bench/results.json."""

import base64
import io
import json
import statistics
from pathlib import Path

from PIL import Image

BENCH = Path(__file__).resolve().parent
# Highlights come from MIT-licensed cases, whose targets can be shown.
HIGHLIGHTS = ["om-20240318", "om-20240225", "om-20240228", "om-20240319"]


def fmt(n):
    return f"{n:,}"


def tradeoff_table():
    tp = BENCH / "tradeoff.json"
    if not tp.exists():
        return "<p class=note>Run bench/tradeoff.py to fill this table.</p>"
    rows = json.loads(tp.read_text())
    rhos = sorted({r["rho"] for r in rows})
    base_total = None
    out = ['<div class="scroll"><table class="tbl"><thead><tr><th>Setting</th>'
           '<th>Targets at 99%+</th><th>At 99.5%+</th><th>Total characters</th>'
           '<th>Median match</th></tr></thead><tbody>']
    for rho in rhos:
        rs = [r for r in rows if r["rho"] == rho]
        total = sum(r["chars"] for r in rs)
        base_total = base_total or total
        label = "default (&rho; = 0.5)" if rho == 0 else f"&rho; = {rho:g}"
        delta = "" if total == base_total else f" <span class=muted>({(total / base_total - 1) * 100:+.0f}%)</span>".replace("-", "\u2212")
        out.append(f"<tr><td>{label}</td><td>{sum(r['match'] >= 99 for r in rs)}</td>"
                   f"<td>{sum(r['match'] >= 99.5 for r in rs)}</td><td>{fmt(total)}{delta}</td>"
                   f"<td>{statistics.median(r['match'] for r in rs):.2f}%</td></tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def png_b64(path, size=(400, 300)):
    im = Image.open(path).convert("RGB")
    if im.size != size:
        im = im.resize(size, Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def main():
    res = json.loads((BENCH / "results.json").read_text())
    # Targets rendered from unlicensed solutions are not redistributed.
    licensed = {c["id"] for c in json.loads((BENCH / "cases.json").read_text()) if c.get("license")}
    v1p = BENCH / "results_v1.json"
    v1 = {r["id"]: r for r in json.loads(v1p.read_text())} if v1p.exists() else {}
    rows = []
    for r in res:
        b = v1.get(r["id"], {})
        rows.append({
            "v1c": b.get("chars"), "v1m": b.get("match"),
            "gradient": isinstance(r["model"]["bg"], dict),
            "id": r["id"], "title": r["title"], "source": r["source"],
            "match": r["match"], "chars": r["chars"], "human": r["human_min_len"],
            "shapes": r["shapes"], "shadows": r["shadows"], "elements": r["elements"],
            "code": r["code"],
            "t": png_b64(BENCH / "human" / f"{r['id']}.png") if r["id"] in licensed else None,
            "o": png_b64(BENCH / "out" / f"{r['id']}.png"),
        })
    rows.sort(key=lambda r: r["t"] is None)        # targets we can show come first
    n = len(rows)
    ok = [r for r in rows if r["match"] >= 99]
    shorter = [r for r in ok if r["chars"] < r["human"]]
    stats = {
        "n": n, "ok": len(ok), "ok98": sum(r["match"] >= 98 for r in rows),
        "shorter": len(shorter),
        "median_ours": round(statistics.median(r["chars"] for r in ok)),
        "median_human": round(statistics.median(r["human"] for r in ok)),
        "median_match": round(statistics.median(r["match"] for r in rows), 2),
        "shadow_cases": sum(r["shadows"] > 0 for r in rows),
        "exact": sum(r["match"] >= 99.995 for r in rows),
        "total": fmt(sum(r["chars"] for r in rows)),
        "gradients": sum(r["gradient"] for r in rows),
    }
    if v1:
        old_rows = [v1[r["id"]] for r in rows if r["id"] in v1]
        stats.update({
            "v1_ok": sum(r["match"] >= 99 for r in old_rows),
            "v1_exact": sum(r["match"] >= 99.995 for r in old_rows),
            "v1_total": fmt(sum(r["chars"] for r in old_rows)),
            "saved_pct": round((1 - sum(r["chars"] for r in rows) / sum(r["chars"] for r in old_rows)) * 100),
        })
    grouped = [r for r in res if "exact_chars" in r and "greedy_chars" in r]
    stats.update({
        "grouped": len(grouped),
        "exact_wins": sum(r["exact_chars"] < r["greedy_chars"] for r in grouped),
        "exact_saved": sum(max(0, r["greedy_chars"] - r["exact_chars"]) for r in grouped),
        "exact_proven": sum(bool(r.get("exact_optimal")) for r in grouped),
    })
    hl = [r for h in HIGHLIGHTS for r in rows if r["id"] == h]
    page = TEMPLATE
    for k, v in stats.items():
        page = page.replace("{{" + k + "}}", str(v))
    page = page.replace("{{DATA}}", json.dumps(rows).replace("</", "<\\/"))
    page = page.replace("{{HIGHLIGHTS}}", json.dumps([r["id"] for r in hl]))
    page = page.replace("{{TRADEOFF}}", tradeoff_table())
    assert "{{" not in page
    out = BENCH / "cssc-results.html"
    out.write_text(page)
    print(f"wrote {out} ({len(page) // 1024} KB)", stats)


TEMPLATE = r"""<title>cssc</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Anybody:wdth,wght@75..150,500;75..150,800&family=IBM+Plex+Sans:wght@400;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* Layout: a wide column; stats strip, three worked examples with their code,
   then the full benchmark as a sortable list of target/output pairs. */
:root {
  --bg: #F1F2F4;
  --surface: #FFFFFF;
  --ink: #17181C;
  --muted: #5D6170;
  --rule: #D9DBE1;
  --accent: #62374E;
  --good: #1F7A4D;
  --warn: #A2560E;
  --display: "Anybody", "Avenir Next Condensed", "Arial Narrow", sans-serif;
  --body: "IBM Plex Sans", "Segoe UI", system-ui, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, Menlo, Consolas, monospace;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --bg: #121317; --surface: #1B1C22; --ink: #E9EAEE; --muted: #9A9EAD;
    --rule: #2D2F38; --accent: #FDC57B; --good: #5CCB8F; --warn: #F0A55B; color-scheme: dark;
  }
}
:root[data-theme="dark"] {
  --bg: #121317; --surface: #1B1C22; --ink: #E9EAEE; --muted: #9A9EAD;
  --rule: #2D2F38; --accent: #FDC57B; --good: #5CCB8F; --warn: #F0A55B; color-scheme: dark;
}
* { box-sizing: border-box; }
body {
  background: var(--bg); color: var(--ink); font: 400 1rem/1.6 var(--body);
  padding-left: max(16px, env(safe-area-inset-left, 0px));
  padding-right: max(16px, env(safe-area-inset-right, 0px));
}
main { max-width: 1060px; margin: 0 auto; padding-block: 2.5rem 4rem; display: grid; gap: 3rem; }
h1, h2 { font-family: var(--display); margin: 0; text-wrap: balance; }
h1 { font-size: clamp(3rem, 9vw, 5.5rem); font-weight: 800; font-stretch: 140%; line-height: 0.9; letter-spacing: -0.02em; }
h2 { font-size: 1.6rem; font-weight: 800; font-stretch: 120%; line-height: 1.1; }
p { margin: 0; max-width: 68ch; }
.lede { font-size: 1.15rem; color: var(--muted); }
.lede b { color: var(--ink); font-weight: 600; }
code, pre, .mono { font-family: var(--mono); }
header { display: grid; gap: 1rem; }
.kicker { font: 500 0.78rem/1 var(--mono); letter-spacing: 0.06em; text-transform: uppercase; color: var(--accent); }
section { display: grid; gap: 1rem; }

.stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 1px; background: var(--rule); border: 1px solid var(--rule); border-radius: 10px; overflow: hidden; }
.stats div { background: var(--surface); padding: 1rem; display: grid; gap: 0.2rem; align-content: start; }
.stats b { font: 800 2rem/1 var(--display); font-stretch: 120%; font-variant-numeric: tabular-nums; }
.stats span { font-size: 0.85rem; color: var(--muted); }
@media (max-width: 700px) { .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); } }

.frame { display: block; width: 100%; height: auto; aspect-ratio: 4 / 3; max-width: 100%; border-radius: 4px; image-rendering: auto; background: var(--rule); }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; }
.pair figure { margin: 0; display: grid; gap: 0.3rem; min-width: 0; }
.pair figcaption { font: 400 0.75rem/1.2 var(--mono); color: var(--muted); }

.hl { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.15fr); gap: 1.25rem; padding: 1.25rem; background: var(--surface); border: 1px solid var(--rule); border-radius: 10px; }
.hl-meta { display: grid; gap: 0.6rem; align-content: start; min-width: 0; }
.hl h3 { margin: 0; font: 800 1.15rem/1.2 var(--display); font-stretch: 115%; }
.hl .why { font-size: 0.95rem; color: var(--muted); }
pre.code { margin: 0; padding: 0.8rem 0.9rem; background: var(--bg); border: 1px solid var(--rule); border-radius: 6px; font-size: 0.78rem; line-height: 1.5; white-space: pre-wrap; word-break: break-all; overflow-wrap: anywhere; max-height: 16rem; overflow: auto; }
.chips { display: flex; flex-wrap: wrap; gap: 0.4rem; }
.chip { font: 500 0.75rem/1 var(--mono); padding: 0.35rem 0.5rem; border-radius: 999px; border: 1px solid var(--rule); color: var(--muted); }
.chip.good { color: var(--good); border-color: color-mix(in srgb, var(--good) 40%, var(--rule)); }
.chip.warn { color: var(--warn); border-color: color-mix(in srgb, var(--warn) 40%, var(--rule)); }
@media (max-width: 760px) { .hl { grid-template-columns: 1fr; } }

.frame.missing { aspect-ratio: 4 / 3; height: auto; display: grid; place-content: center; gap: 0.2rem; padding: 0.5rem; text-align: center; font-size: 0.78rem; color: var(--muted); }
.controls { display: flex; flex-wrap: wrap; gap: 0.6rem 1.2rem; align-items: center; font-size: 0.9rem; color: var(--muted); }
.controls select { font: inherit; color: var(--ink); background: var(--surface); border: 1px solid var(--rule); border-radius: 6px; padding: 0.2rem 0.4rem; }
.seg { display: inline-flex; border: 1px solid var(--rule); border-radius: 6px; overflow: hidden; }
.seg button { font: inherit; font-size: 0.85rem; color: var(--muted); background: var(--surface); border: 0; padding: 0.3rem 0.7rem; cursor: pointer; }
.seg button + button { border-left: 1px solid var(--rule); }
.seg button[aria-pressed="true"] { background: var(--ink); color: var(--bg); }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 300px), 1fr)); gap: 0.9rem; }
.card { background: var(--surface); border: 1px solid var(--rule); border-radius: 10px; padding: 0.7rem; display: grid; gap: 0.55rem; min-width: 0; }
.card-head { display: flex; justify-content: space-between; gap: 0.5rem; align-items: baseline; min-width: 0; }
.card-head span:first-child { font-weight: 600; font-size: 0.9rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.score { font: 500 0.8rem/1 var(--mono); font-variant-numeric: tabular-nums; }
.bar { display: grid; gap: 0.25rem; font: 400 0.72rem/1.2 var(--mono); color: var(--muted); font-variant-numeric: tabular-nums; }
.bar i { display: block; height: 6px; border-radius: 3px; background: var(--rule); position: relative; overflow: hidden; }
.bar i::after { content: ""; position: absolute; inset: 0 auto 0 0; width: var(--w); background: var(--c, var(--accent)); border-radius: 3px; }
details summary { cursor: pointer; font-size: 0.82rem; color: var(--muted); }
details[open] summary { margin-bottom: 0.4rem; }
.note { font-size: 0.88rem; color: var(--muted); }
.muted { color: var(--muted); }
.scroll { overflow-x: auto; border: 1px solid var(--rule); border-radius: 10px; background: var(--surface); }
table.tbl { border-collapse: collapse; width: 100%; font-size: 0.9rem; }
.tbl th, .tbl td { padding: 0.55rem 0.8rem; text-align: right; border-bottom: 1px solid var(--rule); white-space: nowrap; font-variant-numeric: tabular-nums; }
.tbl th:first-child, .tbl td:first-child { text-align: left; }
.tbl thead th { font-weight: 600; font-size: 0.8rem; color: var(--muted); }
.tbl tbody tr:last-child td { border-bottom: 0; }
.tbl tbody tr:first-child td { font-weight: 600; }
.changes { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1rem; }
.change { background: var(--surface); border: 1px solid var(--rule); border-radius: 10px; padding: 1rem; display: grid; gap: 0.45rem; align-content: start; min-width: 0; }
.change h3 { margin: 0; font: 800 1.05rem/1.2 var(--display); font-stretch: 115%; }
.change p { font-size: 0.92rem; color: var(--muted); }
.change code { font-size: 0.85em; }
@media (max-width: 820px) { .changes { grid-template-columns: 1fr; } }
.was { font: 400 0.72rem/1.2 var(--mono); color: var(--muted); font-variant-numeric: tabular-nums; }
ol.steps { margin: 0; padding-left: 1.3rem; display: grid; gap: 0.7rem; max-width: 72ch; }
ol.steps b { font-weight: 600; }
ul.limits { margin: 0; padding-left: 1.2rem; display: grid; gap: 0.5rem; max-width: 72ch; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
</style>

<main>
  <header>
    <div class="kicker">Prototype · image-to-CSS compiler</div>
    <h1>cssc</h1>
    <p class="lede">Give it a target image from <b>CSSBattle</b>, the code-golf game where you redraw a 400×300 picture in as few characters of HTML and CSS as you can. It returns the code. Every result below was rendered by Chromium from the generated code and compared pixel by pixel with the target.</p>
  </header>

  <section aria-label="Summary">
    <div class="stats">
      <div><b>{{ok}}/{{n}}</b><span>targets at 99% match or better ({{ok98}} at 98%+)</span></div>
      <div><b>{{median_ours}}</b><span>median characters on those</span></div>
      <div><b>{{median_human}}</b><span>median for the human solutions, minified</span></div>
      <div><b>{{shorter}}</b><span>of those shorter than the human code</span></div>
    </div>
    <div class="stats" style="margin-top:1rem">
      <div><b>{{v1_ok}} &rarr; {{ok}}</b><span>targets at 99%+ match, first version &rarr; now</span></div>
      <div><b>{{v1_exact}} &rarr; {{exact}}</b><span>pixel-perfect matches</span></div>
      <div><b>{{v1_total}} &rarr; {{total}}</b><span>characters across all targets</span></div>
      <div><b>&minus;{{saved_pct}}%</b><span>total code length since the first version</span></div>
    </div>
    <p class="note">Match counts pixels whose color is within 8/255 per channel of the target. The human solutions come from two public GitHub repos and are written to be readable, not golfed. Top CSSBattle players are far shorter, so these lengths are a baseline, not a leaderboard. The first version was rendered on Linux, like the targets; the current results were rendered on macOS, whose Chromium draws some edges slightly differently (about 0.2% of pixels on average), so match scores across the two are not exactly comparable.</p>
  </section>

  <section aria-labelledby="h-new">
    <h2 id="h-new">What changed since the first version</h2>
    <div class="changes">
      <article class="change">
        <h3>Outline polygons</h3>
        <p>Polygons used to come only from a region's convex hull, with at most five vertices, so a notched or many-sided figure was tiled from slivers. The search now also traces each region's outline, which may be concave, and simplifies it to 4&ndash;12 vertices; a clean-up move then drops vertices while that lowers the score. Missing Piece went from 1,887 to 336 characters, shorter than the human solution.</p>
      </article>
      <article class="change">
        <h3>Gradient backgrounds</h3>
        <p>For striped pictures the compiler fits a hard-stop <code>linear-gradient</code> at any angle: every pixel is projected onto the gradient line, and dynamic programming picks the band boundaries that minimize wrong pixels plus a cost per stop. Shapes are then layered on top as before. {{gradients}} targets use one.</p>
      </article>
      <article class="change">
        <h3>Exactly optimal shadow grouping</h3>
        <p>Choosing which shapes become <code>box-shadow</code>s of which, together with a valid paint order, is now solved exactly with a constraint solver: each shape gets a paint position, shadows share their anchor's, and every pair that must stay in order needs strictly increasing positions unless they share a group. Of {{grouped}} targets with any grouping, it beat the greedy grouping on {{exact_wins}} ({{exact_saved}} characters) and proved optimality on {{exact_proven}}.</p>
      </article>
      <article class="change">
        <h3>Scoring by code length</h3>
        <p>Every variant is now judged by one objective: characters + wrong pixels &divide; &rho;. A clean-up pass drops shapes, snaps near-equal shapes to identical sizes so they can share CSS, and evens out sizes for the shorter <code>padding</code> form, keeping each move only if the objective improves. The shared style element also moved to the end of the document, unclosed, which saves 9 characters wherever it is used.</p>
      </article>
    </div>
  </section>

  <section aria-labelledby="h-hl">
    <h2 id="h-hl">What the compiler found</h2>
    <div id="highlights" style="display:grid;gap:1rem"></div>
  </section>

  <section aria-labelledby="h-all">
    <h2 id="h-all">All {{n}} targets</h2>
    <div class="controls">
      <div class="seg" role="group" aria-label="Filter">
        <button type="button" data-f="all" aria-pressed="true">All</button>
        <button type="button" data-f="ok" aria-pressed="false">99%+</button>
        <button type="button" data-f="miss" aria-pressed="false">Below 99%</button>
      </div>
      <label for="sort">Sort
        <select id="sort">
          <option value="id">Source order</option>
          <option value="match">Match, worst first</option>
          <option value="ratio">Length vs human, best first</option>
          <option value="chars">Shortest code first</option>
        </select>
      </label>
    </div>
    <div class="grid" id="grid"></div>
  </section>

  <section aria-labelledby="h-trade">
    <h2 id="h-trade">Trading match for length</h2>
    <p>&rho; is how many wrong pixels the compiler accepts to save one character. CSSBattle tells players to reach a 100% match before cutting characters, so the default is cautious. Raising &rho; golfs harder. Each row below is the whole benchmark re-run at that setting, rendered in Chromium and scored.</p>
    {{TRADEOFF}}
  </section>

  <section aria-labelledby="h-how">
    <h2 id="h-how">How it works</h2>
    <ol class="steps">
      <li><b>Palette.</b> Find the flat colors and assign each pixel to one. A color that sits between two others counts as antialiasing only if it forms thin lines; a solid patch of it is a real fill.</li>
      <li><b>Base layer.</b> A flat background color, or for striped pictures a hard-stop linear gradient fitted at any angle.</li>
      <li><b>Layered search.</b> Repeatedly add the shape that fixes the most wrong pixels: a box with any corner radii, an ellipse, a rotated bar, or a polygon clipped with <code>clip-path</code>, fitted to the region's convex hull or traced from its outline, concave or not. A new shape can go at any depth in the stack, not just on top. That is how rings, eyes and other nested figures get built.</li>
      <li><b>Refine.</b> Merge two pieces of the same color into one shape when that costs almost nothing, re-fit every shape against its final surroundings, drop shapes that no longer pay for their characters, and round coordinates where that changes no pixels.</li>
      <li><b>Code generation.</b> A shape that is a shifted, uniformly grown or shrunk copy of another becomes a <code>box-shadow</code> of it, when the paint order allows and CSS keeps the shape exact (a spread larger than the corner radius bends the corners). The grouping and the paint order are chosen together by an exact solver. Boxes are sized with unitless <code>padding</code> (allowed in quirks mode), saturated corner radii get short spellings like <code>7em</code>, and properties shared by every element move into one rule in a trailing, unclosed <code>&lt;style&gt;</code>.</li>
      <li><b>Choose.</b> Nine search settings run per image; each result is cleaned up for length and scored by characters + wrong pixels &divide; &rho;. The lowest score wins.</li>
    </ol>
  </section>

  <section aria-labelledby="h-limits">
    <h2 id="h-limits">Limits of this prototype</h2>
    <ul class="limits">
      <li>No borders, text or filters yet, and gradients only on the background, so targets built from those come out longer or less exact.</li>
      <li>The search is greedy with local refinement, so it can miss a cleverer decomposition that a golfer would see.</li>
      <li>Colors are reproduced exactly; the code does not trade color accuracy for shorter color names.</li>
      <li>My rasterizer's antialiasing differs slightly from Chromium's on long diagonal edges, which costs about a point of match on the striped flags.</li>
    </ul>
  </section>
</main>

<script>
(() => {
  const rows = {{DATA}};
  const hlIds = {{HIGHLIGHTS}};
  const byId = Object.fromEntries(rows.map(r => [r.id, r]));
  const WHY = {
    'om-20240318': 'A concave twelve-sided figure: one element clipped by a polygon traced from the region outline.',
    'om-20240225': 'The purple frame is the spread of a pink box\'s shadow; the eight bars are two elements and their shadow copies.',
    'om-20240228': 'The vertical stripes are one hard-stop gradient on the body; the corners and steps are boxes and shadows on top.',
    'om-20240319': 'Mirrored pieces become box-shadows of one another.'
  };
  const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
  const summary = r => r.shapes === 0 ? '' : `${plural(r.shapes, 'shape')} became ${plural(r.elements, 'element')}` +
    (r.shadows ? `; ${r.shadows} ${r.shadows === 1 ? 'is a box-shadow' : 'are box-shadows'}.` : '.');
  const esc = s => s.replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
  const img = (b64, alt) => b64
    ? `<img class="frame" alt="${esc(alt)}" src="data:image/png;base64,${b64}" width="400" height="300" loading="lazy">`
    : `<div class="frame missing"><span>Target not included</span><span>its source has no license; <code>bench/fetch.py</code> renders it locally</span></div>`;
  const matchChip = r => `<span class="chip ${r.match >= 99 ? 'good' : 'warn'}">${r.match.toFixed(2)}% match</span>`;

  document.getElementById('highlights').innerHTML = hlIds.map(id => {
    const r = byId[id];
    return `<article class="hl">
      <div class="pair">
        <figure>${img(r.t, r.title + ' target')}<figcaption>target</figcaption></figure>
        <figure>${img(r.o, r.title + ' rendered from generated code')}<figcaption>generated code, rendered</figcaption></figure>
      </div>
      <div class="hl-meta">
        <h3>${esc(r.title)}</h3>
        <p class="why">${esc((WHY[id] || '') + ' ' + summary(r))}</p>
        <div class="chips">${matchChip(r)}<span class="chip">${r.chars} chars</span><span class="chip">human ${r.human}</span></div>
        <pre class="code">${esc(r.code)}</pre>
      </div>
    </article>`;
  }).join('');

  const grid = document.getElementById('grid');
  const sortSel = document.getElementById('sort');
  let filter = 'all';

  function render() {
    let list = rows.slice();
    if (filter === 'ok') list = list.filter(r => r.match >= 99);
    if (filter === 'miss') list = list.filter(r => r.match < 99);
    const s = sortSel.value;
    if (s === 'match') list.sort((a, b) => a.match - b.match);
    if (s === 'ratio') list.sort((a, b) => a.chars / a.human - b.chars / b.human);
    if (s === 'chars') list.sort((a, b) => a.chars - b.chars);
    const maxLen = Math.max(...rows.map(r => Math.max(r.chars, r.human)));
    grid.innerHTML = list.map(r => `<article class="card">
      <div class="card-head"><span title="${esc(r.title)}">${esc(r.title)}</span><span class="score" style="color:var(${r.match >= 99 ? '--good' : '--warn'})">${r.match.toFixed(2)}%</span></div>
      <div class="pair"><figure>${img(r.t, r.title + ' target')}</figure><figure>${img(r.o, r.title + ' generated')}</figure></div>
      <div class="bar">ours ${r.chars} chars<i style="--w:${(r.chars / maxLen * 100).toFixed(1)}%"></i></div>
      <div class="bar">human ${r.human} chars<i style="--w:${(r.human / maxLen * 100).toFixed(1)}%;--c:var(--muted)"></i></div>
      ${r.v1c ? `<div class="was">first version: ${r.v1c} chars, ${r.v1m.toFixed(2)}%</div>` : ''}
      <details><summary>Code · ${r.shapes} shapes, ${r.shadows} as shadows</summary><pre class="code">${esc(r.code)}</pre></details>
    </article>`).join('');
  }
  document.querySelectorAll('.seg button').forEach(b => b.addEventListener('click', () => {
    filter = b.dataset.f;
    document.querySelectorAll('.seg button').forEach(x => x.setAttribute('aria-pressed', x === b ? 'true' : 'false'));
    render();
  }));
  sortSel.addEventListener('change', render);
  render();
})();
</script>
"""

if __name__ == "__main__":
    main()

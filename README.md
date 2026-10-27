# cssynth

A compiler from images to short HTML/CSS. It is aimed at
[CSSBattle](https://cssbattle.dev) targets: flat 400×300 pictures that players
redraw in as few characters as they can.

<table>
<tr><th>Target</th><th>Rendered from cssynth's output</th></tr>
<tr>
<td><img src="bench/human/om-20240318.png" width="300" alt="Target: a dark red arch with a stepped notch on a red background"></td>
<td><img src="bench/out/om-20240318.png" width="300" alt="The same arch, rendered in Chromium from the generated code"></td>
</tr>
</table>

```html
<body bgcolor=c31c1d><b style="position:fixed;inset:70px 80px 70px 80px;background:#660301;clip-path:polygon(25% 0,75% 0,100% 100%,75% 100%,75% 75%,140px 75%,140px 50%,100px 50%,100px 75%,25% 75%,25% 100%,0 100%)">
```

214 characters, a 99.9% pixel match. The human solution it was rendered from
is 493 characters even after minifying.

<img src="docs/demo.gif" width="640" alt="The in-browser demo: a saved result shows at once; then a green I-beam is picked, compiled in the browser into 532 characters, downloaded as HTML, and the downloaded file, opened on its own at 400×300, matches the target">

The [in-browser demo](https://fmindstormer.github.io/cssynth/demo/): pick a
target, compile, read the code, download it and open the file on its own.
The waits for Python to load and for the compile are cut from the recording;
the captions give their real length (`demo/record.js` made it).

**[See all 66 targets, outputs and generated code on the results page →](https://fmindstormer.github.io/cssynth/)**

**[Try it on your own picture, in your browser →](https://fmindstormer.github.io/cssynth/demo/)**

**[Read how it works →](https://fmindstormer.github.io/cssynth/blog/)**

## Results

On the 66 targets of the development set (the ones the compiler was developed
on; held-out results are [below](#beyond-the-development-set)), rendered in
Chromium and compared pixel by pixel:

| | |
|---|---|
| Shorter than the human solution (minified) | **56 of 66** |
| Total code length | **23,329** characters (human: 35,532) |
| Targets at ≥ 99% pixel match | **66 of 66** (lowest 99.21%) |
| Mean pixel match | 99.82% |

The human solutions are readable code from two public repositories, minified
but not golfed. Top CSSBattle players write far shorter code, so these
lengths are a baseline, not a leaderboard. The full results, with every
target, output and generated program, are on the
[results page](https://fmindstormer.github.io/cssynth/) (built from
`bench/cssynth-results.html`).

### What each part buys

Each row recompiles all 66 targets with one technique switched off
(`bench/ablation.py`, run by the **Ablation** workflow). Scores come from
cssynth's own rasterizer rather than Chromium, and the parts overlap, so the
rows don't add up.

| Switched off | Total J | Characters | Shorter than human |
|---|---|---|---|
| nothing (full compiler) | 60,441 | 23,329 | 56 / 66 |
| Insertion at any depth (shapes go on top) | 64,637 (+6.9%) | 24,887 (+1,558) | 54 / 66 |
| Polygons traced from outlines | 64,449 (+6.6%) | 25,791 (+2,462) | 52 / 66 |
| Re-search of the best result | 64,444 (+6.6%) | 24,652 (+1,323) | 55 / 66 |
| Gradient backgrounds | 63,265 (+4.7%) | 24,077 (+748) | 54 / 66 |
| Length-aware shape choice (by pixels only) | 62,921 (+4.1%) | 24,017 (+688) | 54 / 66 |
| Length-aware clean-up | 61,982 (+2.5%) | 24,914 (+1,585) | 52 / 66 |
| Splitting regions that touch at corners | 61,705 (+2.1%) | 24,005 (+676) | 55 / 66 |
| Nested-ring motifs | 61,309 (+1.4%) | 23,495 (+166) | 56 / 66 |
| Box-shadows | 61,258 (+1.4%) | 24,150 (+821) | 56 / 66 |
| Soft gradient stops | 61,106 (+1.1%) | 23,680 (+351) | 55 / 66 |
| Per-tag rules (`<i>`, `<u>`, `<s>`) | 60,807 (+0.6%) | 23,583 (+254) | 55 / 66 |
| `clip-path` reuse for copies and mirrors | 60,708 (+0.4%) | 23,544 (+215) | 55 / 66 |
| Exact (CP-SAT) shadow grouping, greedy kept | 60,554 (+0.2%) | 23,442 (+113) | 56 / 66 |

Inserting shapes below existing ones, outline polygons and the re-search
matter most; gradient backgrounds and choosing shapes by length as well as
pixels come next. Exact shadow grouping and `clip-path` reuse are small on
average but decide a few targets.

### Beyond the development set

The 66 targets are where the compiler was developed, so two more benchmarks
test it elsewhere (details in [docs/method.md](docs/method.md#beyond-the-development-set)).

**Held-out structural families.** 48 targets generated from six structures:
mirrored shapes, repeats, concentric rings, petals, stripes and unrelated
shapes. They are compiled once per version, never inspected, and scored in
Chromium (`bench/evaluate.py`). The second baseline climbs 40% more starts,
to spend at least the CPU time the motif search does:

| | solved (≥ 99%) | characters, on the 40 all solve | CPU |
|---|---|---|---|
| v0.5.0 | 40 / 48 | 11,944 | 2,634 s |
| v0.5.0, 14 starts per step | 41 / 48 | **11,240** | 3,177 s |
| with nested-ring motifs | **43 / 48** | 11,627 | **2,311 s** |

The motifs solve the most with the least time. The baseline with more starts
writes 3.4% less code on the targets all three solve, but that rests on three
scatter and petals targets: it is shorter on 6 and longer on 7, and the 95%
bootstrap interval runs from 2.1% shorter to 9.6% longer. Giving the default
more starts makes its code longer, not shorter (+6.5% on the development
split). (This is the third
held-out set; the earlier two were spent on earlier versions, see
[docs/method.md](docs/method.md#motifs).)

**Known optima.** On 40 tiny targets (up to four grid-aligned boxes and
ellipses), an exact solver finds the shortest program that cssynth's own
emitter can write. cssynth reproduces 35 exactly and is optimal on 33 of
them (30 before this round); the other two are 40 characters over.

Petals (leaves turned about a center) remain the weak family: Chromium
antialiases turned and curved edges differently from cssynth's model, so the
right program looks wrong to the search.

## Usage

```sh
pip install .
cssynth target.png           # prints the code; length and details on stderr
cssynth -v target.png        # also logs the search
cssynth --rho 2 target.png   # golf harder (see "Objective")
cssynth --fast target.png    # skip the re-search: about 2x faster, longer code
```

From Python:

```python
from cssynth import compile_image
code, info, model = compile_image("target.png")
```

## Objective

Everything is scored by one number:

    J = characters + wrong pixels / rho

`rho` is how many wrong pixels the compiler accepts to save one character
(default 0.5). CSSBattle tells players to reach a 100% match before cutting
characters, so the default is cautious; `bench/tradeoff.py` measures what
larger values buy.

## How it works

A longer write-up of the method, with the reasoning behind each part, is in
[docs/method.md](docs/method.md).

```mermaid
flowchart LR
    A[target PNG] --> B[palette]
    B --> C[base layer<br>color or gradient]
    C --> D[layered greedy search]
    D --> E[refine]
    E --> F[simplify for length]
    F --> G[code generation]
    G --> H{lowest J<br>of 16 variants}
    H --> I[re-search parts<br>of the best]
```

1. **Palette** (`search.extract_palette`): flat colors with at least 40
   pixels. A color lying between two others counts as antialiasing only when
   its pixels form thin lines (nothing survives one erosion); a solid region
   of such a color is a real fill, e.g. a semi-transparent shape.
2. **Base layer**: a flat background color, or for striped pictures a
   hard-stop `linear-gradient` (`search.fit_gradient`). Every pixel center is
   projected onto the gradient line for each angle (1° scan, then refined);
   dynamic programming over 1-px bins then chooses band boundaries minimizing
   wrong pixels + a penalty per stop. Chromium evaluates gradients at pixel
   centers and does not antialias hard stops, so a target edge drawn by a
   rotated box leaves a band of wrong pixels; each boundary is then moved to
   a sub-pixel position and given a short linear ramp (a soft stop, `#a
   159.5px,#b 160.5px`) where that pays for its characters. Chromium draws
   these within 3/255 of the model.
3. **Layered greedy search** (`search.greedy`): repeatedly add the shape that
   fixes the most wrong pixels, or, in the length-aware mode, the one with the
   best pixels fixed / rho minus its estimated characters (its own element, or
   a box-shadow entry when it is a shifted copy of a shape already placed). Candidates come from connected regions of wrong
   pixels (and, where a region only holds together at corners, from each of its
   edge-connected parts): boxes, ellipses, boxes with various corner radii, a
   45° diamond, a plain and a rounded bar along the region's principal axis, a
   leaf (a square rounded on two opposite corners, turned onto that axis), and
   `clip-path` polygons, both from
   the region's convex hull (3–5 vertices) and traced from its outline, which
   may be concave (4–12 vertices, simplified by Visvalingam's algorithm). The
   plain bounding box of each color's largest regions is always climbed too:
   from there a climb peels a compound region (a cross, an I-beam) down to its
   biggest bar. The best starts (each at its best depth) are hill-climbed on
   their edges, radii, rotation or vertices; a gain is a few lookups in
   running sums along pixel rows, over the runs of pixels a shape covers
   (cached by shape, and exact: see docs/method.md).
   A shape may be inserted **at any depth** in the stack: for each
   depth the gain is computed against the canvas below it and only the pixels
   that the shapes above leave visible. This is what lets it build rings and
   nested figures.
4. **Refine** (`search.refine`): merge two touching same-color shapes into one
   when that costs fewer than `min_gain` pixels; re-fit each shape against its
   final surroundings; delete shapes that no longer fix enough pixels; snap
   coordinates to multiples of 5/10 when it changes nothing.
5. **Simplify for length** (`simplify.simplify`): local moves scored by J,
   with code length measured by running the real code generator: drop a
   shape; drop a polygon vertex and re-fit; snap two near-equal shapes to
   identical (or uniformly grown) geometry so they can become box-shadows of
   one another or share CSS (also turned copies at different angles), then
   re-position; make odd sizes even so `padding` can size the box.
6. **Code generation** (`codegen.emit`):
   - paint-order constraints: shape *i* must stay below *j* if they overlap
     with different colors;
   - **box-shadow grouping**, solved exactly (`make_groups_exact`, CP-SAT):
     each shape is an element or a shadow of one compatible element; each
     gets a paint position, shadows share their anchor's, and for every
     constrained pair (i below j) the positions strictly increase unless both
     are in the same group, which excludes cycles between groups. The
     objective is the characters of elements, shadow entries and
     `box-shadow:` overhead. A greedy grouping also runs; the shorter final
     code wins;
   - box-shadow spreads are only used where CSS keeps the shape exact (CSS
     bends a shadow's corner radius when the spread exceeds it);
   - elements are unclosed `<b>` tags with `position:fixed`, except rotated or
     clipped ones, which are closed because they'd transform/clip descendants;
   - sizes via unitless `padding` (quirks mode) or `inset` when shorter;
   - saturated corner radii get the shortest equivalent spelling (`7em`);
   - shortest color spelling; background via `<body bgcolor=...>` or a
     gradient rule;
   - properties shared by every element move into one `b{...}` rule, in a
     `<style>` at the very end of the document, left unclosed along with its
     last rule (the parser closes both at end of input);
   - families of alike elements (same size and corners, same color, or both)
     can move to their own tag, `<i>`, `<u>` or `<s>`, with their own rule,
     which is how copies of a shape at different angles share their CSS;
   - a polygon that is a copy or mirror image of another reuses its
     `clip-path` with `scale:-1 1`, `1 -1` or `-1`, so the two can share it
     in a rule (the clean-up snaps near-mirrors to exact ones).
7. **Choose** (`compiler.VARIANTS`): six searches run per image, each in both
   modes, by pixels and length-aware; two of them also report where a higher
   `min_gain` would have stopped, so there are 16 results. Each is simplified
   and scored by J, and the lowest J wins. Outline polygons run as separate
   variants because the greedy search can also take them where boxes and
   shadows would end up shorter. The length-aware mode wins on most targets,
   but not all: it can pick a cheap shape that leaves more for later.
8. **Re-search** (`improve.improve`): the greedy search commits to shapes in
   the order they first help, so an early polygon can take a region that a
   shorter primitive would have drawn. The best result is taken apart and
   refilled: one polygon at a time (refilled without polygons of its color),
   then every shape of one color (refilled as before, and without polygons).
   Refills use the winning variant's mode. Each is refined and simplified,
   and kept when J drops. `--fast`
   skips this step.

## Benchmark

`bench/` holds the 66 cases (`cases.json`), the generated code and its renders
(`out/`), and the scores (`results.json`, plus `results_v1.json` and `out_v1/`
from the first version for comparison).

Targets are Chromium renders of public human solutions, so each target is
exactly reproducible. Match = share of pixels within 8/255 per channel of the
target, measured on Chromium's render of the generated code.

- 31 cases come from [OmPreetham/cssbattle](https://github.com/OmPreetham/cssbattle)
  (MIT); their code and targets are included.
- 35 come from [Kushalshakya/CSSBattle](https://github.com/Kushalshakya/CSSBattle),
  which has no license, so the repository keeps only their metadata.
  `bench/fetch.py` downloads them at a pinned commit, checks them against
  `cases.json` and renders the targets. See [THIRD_PARTY.md](THIRD_PARTY.md).

```sh
cd bench && npm ci && cd ..         # puppeteer-core + @sparticuz/chromium
python bench/fetch.py               # download and render the remaining targets
python bench/run.py                 # compile all, render in Chromium, score
python bench/reemit.py              # re-run only code generation on saved shapes
python bench/tradeoff.py            # characters vs match for several rho
python bench/build_page.py          # results page -> bench/cssynth-results.html

python bench/evaluate.py --set heldout2 --method full    # held-out families, scored in Chromium
python bench/evaluate.py --set heldout2 --compare base full
python bench/tiny.py                # tiny targets against their known optima
python bench/families.py train 8    # a development split of the families
python bench/proposals.py data --out props.pkl   # outcome-labeled motif proposals
```

The targets were rendered with `@sparticuz/chromium` 131 on Linux, which only
runs there. Elsewhere, point `CHROME_PATH` at Chrome for Testing 131
(`npx @puppeteer/browsers install chrome@131.0.6778.204`). Its edges differ
slightly from the Linux build: the human solutions themselves match their
Linux targets by 99.8% on average on macOS (99.1% at worst), which lowers
match scores by the same amount. The generated code is the same on both. The
committed results and the trade-off table come from the **Benchmark**
workflow, which runs everything on Linux (about 35 minutes on GitHub's
runners).

## Development

```sh
pip install -e ".[dev]"
pytest          # unit tests and small end-to-end compiles, ~20 s
ruff check .
```

```
cssynth/
  compiler.py   compile_image: run the variants, simplify, keep the lowest J
  improve.py    re-search: take the best result apart and refill it
  search.py     palette, base layer, greedy shape search, refine
  shapes.py     the Shape model and a rasterizer that predicts Chromium's
  simplify.py   length-aware clean-up moves
  codegen.py    golfed HTML/CSS, including the CP-SAT shadow grouping
bench/          benchmark data, runner and results page
demo/           the in-browser demo (Pyodide) and a local Gradio app
tests/
```

## Open problems

- **Search for structure.** The greedy weighs each shape's length now, and
  proposes nested rings as one step (a filled disc on its own breaks the
  pixels inside it, so one shape at a time never starts a ring). Mirrors and
  turns as motifs rescued some petals but lengthened other targets. A filter
  learned from outcome-labeled proposals didn't transfer to structures it
  hadn't seen (docs/method.md). Otherwise the search still goes one shape at
  a time, and the re-search only repairs its choices locally. Two light circles stacked on an oval (2024-02-27) become one tall
  rounded box plus patches, because the box fixes more pixels than either
  circle, and a climb from one circle grows back into the box. The lotus is
  drawn with polygons where a golfer uses three rotated leaves. Comparing
  whole programs (two circles plus a cheap shadow against a box plus
  patches) is the next step. A beam over partial J is not enough on its
  own: the two-circle branch trails for two steps before it pulls ahead,
  and the climbs never propose a lone circle to start it.
- **Reuse.** Turned copies of a box share a rule and mirrored copies of a
  polygon share a `clip-path`, but nothing yet uses `::before`/`::after` to
  repeat a shape, or mirrors a rounded box.
- **More primitives.** Gradients on boxes (not only the background), borders
  (only a handful of the human solutions use them, for frames and outlined
  shapes), text. Two were measured and left out: `repeating-*-gradient` (only
  one benchmark target repeats a band pattern, and its output is already half
  the human length) and a `radial-gradient` background for a circle (8
  targets start with one, but `circle at …` plus soft stops costs about as
  much as the element; at best 34 characters in total).
- **Antialiasing.** A soft stop's linear ramp only approximates how Chromium
  smooths a rotated edge, so striped flags still carry a few hundred wrong
  pixels, and so do some rotated shapes. On curved edges Chromium's ramp is
  about twice as wide as box filtering, and uneven (measured in
  `docs/method.md`). The exact program for two turned leaves scores 599
  wrong pixels in the model, which is why petals are the weakest held-out
  family.
- **Speed.** A full benchmark run takes about 43 CPU-minutes on an Apple M4
  (and about two hours on GitHub's slower runners), most of it in hill
  climbs. Exact cached gains cut that by about 40% without changing any
  output. A small network that picks which starts to climb was tried
  (docs/method.md): it beats ranking by initial gain, but pruning still
  cost 1.9% in J for 29% less time, so it is not used.

## License

MIT, see [LICENSE](LICENSE). Third-party benchmark material is described in
[THIRD_PARTY.md](THIRD_PARTY.md). Not affiliated with CSSBattle.

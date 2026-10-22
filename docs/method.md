# How cssynth works

cssynth turns a flat 400×300 picture into the shortest HTML/CSS it can find
that draws it. This note explains the ideas behind it: what it optimizes,
how it searches, how it turns shapes into golfed code, and how it keeps its
own picture of the result honest against what Chromium actually draws.

## The problem

[CSSBattle](https://cssbattle.dev) shows a target picture; players write
HTML/CSS that renders it in a 400×300 frame, and the shortest code with a
full match wins. The pictures are flat: a few solid colors, boxes, circles,
rounded corners, triangles, the odd rotated bar.

Two things make this a compiler problem rather than an image-fitting one:

- **The cost is characters, not shapes.** A circle (`border-radius:50%`) is
  cheap; a five-point `clip-path:polygon(...)` costs 40–60 characters; a
  shape that repeats can be a `box-shadow` of another for 10–20. The best
  decomposition is the one with the shortest *code*, which is not the one
  with the fewest shapes.
- **The renderer is fixed.** Chromium decides where each edge falls,
  how it is antialiased, how a rotated box is rounded to pixels. A plan that
  looks right in an idealized model can be off by a pixel band everywhere.

## One objective

Everything is scored by one number,

    J = characters + wrong pixels / rho

where a pixel is wrong if any channel differs from the target by more than
8/255, and `rho` is how many wrong pixels the compiler accepts to save one
character (default 0.5: two wrong pixels cost one character, so it almost
never trades accuracy for length). Search variants, clean-up moves and
re-search steps are all accepted or rejected by J, with the character count
measured by running the real code generator rather than estimated.

## Shapes

A picture is modeled as a base layer plus a stack of shapes painted in
order:

- **Base layer:** a flat color, or a hard-stop `linear-gradient` at any
  angle for striped pictures. The gradient is fitted by projecting every
  pixel center onto the gradient line and choosing band boundaries by
  dynamic programming (mismatched pixels plus a penalty per stop), first on
  a 1° scan of angles, then refined.
- **Shapes:** a CSS box with a position, a size, a color, four corner radii
  (or `50%` for an ellipse), a rotation, or a `clip-path` polygon.

The rasterizer that scores a stack mirrors Chromium's rules where they
matter: boxes are sampled at pixel centers; CSS scales oversized corner
radii down proportionally; a rotated box's fractional position is rounded
to whole pixels before rotating; a hard gradient stop is not antialiased.

## Search

### Layered greedy search

The core loop adds one shape at a time: the shape that fixes the most wrong
pixels. Two details make it far stronger than painting on top:

1. **Insertion at any depth.** A new shape can go anywhere in the stack. For
   depth *k*, its gain is computed against the canvas *below* that depth and
   only over the pixels that the shapes *above* leave visible. This is how
   rings, eyes and nested figures get built: the outer disc is added after the
   inner one but slides underneath it.
2. **Candidates from the error.** Proposals come from connected regions of
   still-wrong pixels of one color: the region's box, ellipse, boxes with
   various corner radii, a 45° diamond, a bar, rounded bar and leaf along the
   region's principal axis, and polygons, both from the convex hull (3–5
   vertices) and traced from the region's outline (4–12 vertices,
   Visvalingam simplification). Regions that only hold together at a corner
   also contribute their edge-connected parts, since no single shape fits two
   squares that touch diagonally.

The best starts are hill-climbed: move each edge, grow or shrink, move
corner radii, rotate, move polygon vertices, at step sizes 16 down to 1.

### Making evaluation cheap, exactly

Hill climbing evaluates over a million candidate shapes on a busy target, so
the gain function is the hot loop. A gain is a sum of (fixable − breakable)
over the pixels a shape covers. The search keeps running sums of that along
each pixel row and describes each shape by the runs of pixels it covers in
each row, so a gain is two lookups per run. All of it is exact:

- **Plain boxes** use a summed-area table instead: four lookups.
- **Rounded boxes** cover one run per row, shortened by what each corner cuts
  away. Within a row, a corner cuts the pixels nearest the box's side, so a
  count per row places the cut, and the counts use the rasterizer's own
  floating-point expression. When the box's center and arc centers are
  multiples of 1/64 (they nearly always are), every offset from an arc's
  center is exact, so the counts depend only on those offsets and are
  cached: a moved or resized box reuses its corners.
- **Polygons** cover, in each row, the spans between pairs of sorted edge
  crossings. The crossings use the same arithmetic and the same "center left
  of the crossing" test as the rasterizer.
- **Turned boxes** take their runs from the rasterizer's mask.

Runs are cached by geometry. Each greedy step re-climbs from much the same
starts against new pixels, so about half of all evaluations hit the cache.
Code generation caches each shape's CSS for the same reason: the clean-up
re-emits the same shapes thousands of times. Every shortcut was checked
against the full rasterizer on 100,000 random shapes, and the compiler's
output is the same, byte for byte, on all 66 targets, on macOS and on
Linux. The whole benchmark takes 43 CPU-minutes on an Apple M4 against 75
before the caches (single-target runs on a GitHub runner: 36–37% less),
and the in-browser demo compiles its examples about twice as fast.

### Variants and shared searches

The greedy search has a few knobs: how many pixels a shape must fix
(`min_gain`), whether bounding boxes are always climbed, flat or gradient
base, whether outline polygons are proposed, and how each step chooses
(below). Sixteen settings run per image and the lowest J wins. A run with a higher `min_gain` mostly retraces the
lower one and stops where nothing fixes enough pixels, so one search reports
both: on the benchmark this gives exactly the same results as running them
separately.

### Length in the loop

Picking the shape that fixes the most pixels ignores what it costs to
write: a five-point polygon and a box that fix about as many pixels look
the same. In the length-aware mode, each step instead picks the climbed
shape with the best

    pixels fixed / rho − estimated characters

where the estimate is the shape's own element, or a box-shadow entry when it
is a shifted copy of a shape already placed (so repeats get cheaper as the
search goes). Every search runs in both modes. On the benchmark the
length-aware mode wins on 50 of 66 targets, but the other mode still wins on
some: a cheap shape now can leave more to draw later. Running both lowers
the total J by 4.1% and the characters by 688. Twice the searches cost
about the same time as before, because the length-aware searches end with
fewer shapes.

### Re-search

The greedy search commits to shapes in the order they first help. An early
polygon can take a region that a shorter primitive would have drawn, and
everything around it is then fitted to that choice. After the variants, the
best result goes through a small large-neighborhood search: remove one
polygon (and forbid polygons of its color), or every shape of one color
(with or without polygons), refill the gap with the greedy search from the
remaining stack (in the winning variant's mode), refine, simplify, and
keep the result if J drops.

### Length-aware clean-up

The search maximizes pixels fixed; the clean-up minimizes J. Its moves:
drop a shape; drop a polygon vertex and re-fit; snap two near-equal shapes
to identical (or uniformly grown) geometry so they can share CSS or become
shadows of one another, including turned copies at different angles; make
odd sizes even so `padding` can size the box.

## Code generation

### Golfing tricks

- No doctype, so the page renders in quirks mode, where `padding:50` and
  `left:20` need no units, and a box can be sized by unitless `padding`.
- Every element is an unclosed `<b>`: fixed-position children still place
  against the viewport, so nesting is harmless. Rotated or clipped elements
  are closed, since they would transform or clip their descendants.
- `<body bgcolor=...>` takes bare hex; colors use the shortest spelling.
- Properties every element shares go into one rule, in a `<style>` at the
  very end of the document, left unclosed along with its last rule (the
  parser closes both). Families of alike elements can take their own tag,
  `<i>`, `<u>` or `<s>`, with their own rule; this is how turned copies of a
  shape share their size, corners and color.
- A polygon that is a copy or a mirror image of another, in a box of the
  same size, reuses its `clip-path` and adds `scale:-1 1`, `1 -1` or `-1`
  (the clip is applied before the transform, so it flips with the box). The
  clean-up snaps near-mirrors to exact mirrors when that lowers J.

### Box-shadow grouping as a constraint problem

A shape that is a translated (and, through spread, uniformly grown or
shrunk) copy of another can be drawn as a `box-shadow` of it, for a fraction
of an element's cost. But a shadow paints just below its element, so
grouping changes the paint order, and shapes that overlap with different
colors must keep their relative order.

cssynth solves the grouping and the paint order together with CP-SAT:

- each shape is either an element (`y_i`) or a shadow of one compatible
  element (`x_ka`);
- each shape gets a paint position `t_i`; a shadow shares its anchor's;
- for every pair that must stay in order (*i* below *j*), `t_i ≤ t_j`, and
  strictly `t_i < t_j` unless both are in the same group;
- minimize the characters of elements, shadow entries and `box-shadow:`
  overheads.

The strict ordering between groups rules out cycles, so a valid paint order
always exists. A greedy grouping runs too, and the shorter final code wins.
Shadows are only used where CSS keeps the shape exact: a spread larger than
a corner radius bends the corner, so those pairs never group.

## Staying honest about rendering

The internal rasterizer drives the search, but the benchmark scores what
Chromium draws: every output is rendered in headless Chromium and compared
pixel by pixel with the target, which is itself Chromium's render of a
human solution. Where the model and Chromium disagreed, the model was fixed
rather than tuned around:

- a rotated box's position is rounded before rotating;
- gradient stops: Chromium evaluates gradients at pixel centers and does not
  antialias hard stops. A target drawn with rotated boxes has antialiased
  edges, so a hard stop leaves a band of wrong pixels along every edge.
  cssynth now fits each boundary to a sub-pixel position with a short linear
  ramp, which Chromium draws exactly as the model predicts (within 3/255);
- a shadow's spread larger than its corner radius changes the corner shape,
  so such shadows are not used.

## Results

On 66 targets rendered from public human solutions, cssynth's code is
shorter than the (minified, not golfed) human solution on 56, and 23,329
characters in total against 35,532, with all 66 at a 99%+ pixel match in
Chromium. See the [README](../README.md#results) and the
[results page](https://fmindstormer.github.io/cssynth/) for every target and
the generated code.

## What each part buys

Switching off one technique at a time and recompiling all 66 targets
(scores from cssynth's own rasterizer; the parts overlap, so the rows don't
add up):

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

The two ideas that shape the search, inserting shapes at any depth and
re-searching the result, are worth the most; so are outline polygons, which
replace stacks of slivers. Code-generation tricks are smaller on average,
but each decides a few targets.

## Experiment: learned start ranking

Each greedy step hill-climbs about 18 starts, and the climbs are most of the
search's time. Could a small network pick the few worth climbing? Trained on
logs from 600 random synthetic scenes (boxes, ellipses, rounded and rotated
shapes, polygons, shifted copies; none of the benchmark targets), a 21-input
MLP (32 and 16 hidden units) scores each start from cheap features: its kind,
initial gain and rank, depth, the step and the color's share of the error.
On held-out scenes it finds the start the full search would choose more often
than ranking by initial gain does:

| starts climbed | MLP finds the chosen start | initial gain finds it |
|---|---|---|
| 3 | 74% | 66% |
| 6 | 88% | 80% |
| 10 | 97% | 96% |

On the 66 benchmark targets, climbing only the top 6:

| | total J | characters | CPU (local) |
|---|---|---|---|
| all starts | 64,474 | 23,826 | 76 min |
| top 6 by the MLP | 65,713 (+1.9%) | 24,495 | 54 min |
| top 6 by initial gain | 68,005 (+5.5%) | 25,427 | 52 min |

The network recovers about two thirds of what naive pruning loses, but the
full search still wins, and a missed start early in a greedy run compounds
(keeping 8 starts happened to score worse than 6, at +3.1%). It is not part of
the compiler; the time is better spent making each climb cheaper.

## Beyond the development set

The 66 targets above are the development set: every technique here was
tuned on them, so they can't show how well the compiler generalizes. Three
more benchmarks do. They are scored by `bench/evaluate.py`, which renders
every output in Chromium, counts a target as solved at a 99%+ pixel match,
compares lengths only on the targets every method solves, and records CPU
time (process time, so running in parallel doesn't inflate it).

**Structural families** (`bench/families.py`). Short CSS programs generated
from six structures: a shape and its mirror image (*mirror*), copies at a
constant offset (*repeat*), concentric circles or squares (*rings*), leaves
turned about a center (*petals*), bands with an emblem (*stripes*), and
unrelated layered shapes as a control (*scatter*). A development split
(seeds 0–7) was used to diagnose failures. Three held-out sets of 8 per
family, from fixed seeds, are committed as programs (`bench/heldout*/`).
Each was compiled once per version under test and spent on one version (see
[Motifs](#motifs)); their pictures were never looked at. The targets are
rendered where they are scored.

**Tiny targets with known optima** (`bench/tiny.py`). Random stacks of up to
four boxes or ellipses on a 10 px grid, one color each. An exact solver lists
every stack in that space that draws the same pixels. It works from the top
down: a shape must cover all pixels of its color and may cover others only
where shapes above hide them. It then takes the shortest code cssynth's own
emitter writes for any of them. Optimum and output come from the same
emitter, so the gap measures the search alone. On 40 targets, before the
changes below, cssynth exactly reproduced 35 and was optimal on 30 of those.
Three of the five gaps were exactly the length of a `border-radius` of 1–4 px
that changed no pixel, which the clean-up never tried to remove. Now it does,
and cssynth is optimal on 33 of 35 (mean gap +2.3 characters, from +5.0). The
two left, 40 characters over each, are a shape split in two and a wrong
stacking order.

## Motifs

A motif is several shapes proposed as one step of the greedy search and
scored, like the alternatives, by what the step leaves: emitted characters
plus wrong pixels / ρ (`cssynth/motifs.py`, `search.best_motif`).

**Nested rings** are the one that pays. Three concentric circles need a
filled disc first, and that disc on its own breaks every correct pixel inside
it, so a search adding one shape at a time never places it. Every rings
target in the development split failed for this reason, ending in hundreds of
characters of slivers at 98%. The nest motif fills a ring-shaped region's
holes, fits a shape to the filled region, recurses into the hole with the
color that lines it, and offers the whole stack at once. The emitter then
often writes it as one element with spread box-shadows:
`<b style="…padding:80;border-radius:50%;box-shadow:0 0 0 15px #1a4341,0 0 0 30px #f3ac3c">`.

A nest is proposed only when the region has exactly one hole. The first
version also nested frames with several windows, fitting one shape over all
the windows; the step rule accepted it and nothing later recovered.

Mirror images, shifted copies and turns were tried too. They were seeded
either from the best climbed shapes, or from a region's detected symmetry (a
half or a sector fitted, climbed and composed). Copies add nothing over
box-shadow grouping, which already finds them. Mirrors and turns rescue some
petals targets but make others longer and cost 2.5× the CPU time, so they
are off by default (`search.MOTIFS`). Development split, first version, runs
in pairs (so CPU times are only comparable within the table), on the 40
targets all four methods solve:

| | solved (≥99%) | characters | CPU |
|---|---|---|---|
| v0.5.0 | 40 / 48 | 11,011 | 3,018 s |
| nested rings | 43 / 48 | 10,936 | 4,242 s |
| nested rings + symmetric pieces | 45 / 48 | 11,611 | 7,428 s |
| the same, accepted by the learned filter (below) | 43 / 48 | 11,715 | 8,259 s |

Smaller fixes found along the way:
- a turned shape can now grow together with its corner radii, so a leaf stays
  a leaf while it climbs;
- colors one or two levels apart are merged into one palette entry (Chromium
  paints a turned element a shade off its unturned twin, which split leaves
  into two colors);
- the clean-up tries squaring rounded corners.

**Only in half the variants.** A nest that wins its step can still leave a
worse result: on two development targets it did, adding up to 400
characters. The compiler already runs 12 search variants and keeps the best
finished result, so motifs are proposed only in the six that choose shapes by
pixels alone. A step-wise mistake there can't beat a good result from the
other six, and the motif search costs half as much.

**Compared at equal compute.** Each method below ran alone, one after
another. The baseline gets a larger budget: 14 starts climbed per step
instead of 10, which costs at least what the motifs do. Lengths are on the
targets all three solve.

| | dev split of the families (48) | the 66 dev targets (macOS Chromium) | third held-out set (48) |
|---|---|---|---|
| v0.5.0 | 40 solved, 11,011 ch, 2,036 s | 64 solved, 22,900 ch, 1,963 s | 40 solved, 11,944 ch, 2,634 s |
| v0.5.0, 14 starts | 41 solved, 11,276 ch, 2,269 s | 64 solved, 23,092 ch, 2,448 s | 41 solved, **11,240** ch, 3,177 s |
| motifs + fixes (default) | **43** solved, **10,576** ch, **1,807** s | **66** solved, **22,445** ch, 2,210 s | **43** solved, 11,627 ch, **2,311** s |

On the held-out set the default solves the most targets, with the least CPU
time. But on the 40 targets all three solve, the baseline with more starts
writes 3.4% less code. Its extra climbs pay off on scatter and petals, where
motifs don't apply.

**The held-out sets, honestly.** Each held-out set is compiled once per
version, and its pictures are never looked at. The first was spent on the
first version, which also nested frames with several windows and used a
wider tolerance at edges. Compared with v0.5.0 it solved one more target, but
wrote 5% more characters on the targets both solved and took 57% more CPU
time. The regressions were then diagnosed on the development split.

The second set was spent on the revised version, with nests in every
variant: 37 solved against 34 for v0.5.0 (and 34 with more starts), 9,876
characters against 9,994 (and 9,912), and 3,405 s against 3,029 s (and
3,614 s).

On the 66 development targets that version still lost 400 characters on two
of them, so motifs moved to half the variants (above). The third set was
spent on that, which is the shipped version.

**Rendering, again.** Chromium's edge on a turned straight side matches box
filtering. On curved sides (rounded corners, leaves) the ramp has tails out
to ±1.25 px, about twice as wide. Measured on calibration renders of turned
squares and rounded squares at 0–90°, the per-pixel spread around any fitted
profile is about 7%, more than the 3% tolerance allows at high contrast. A
fitted profile per edge type halved the errors on a square at 45° but
tripled them on an unturned rounded square, so it was not adopted. A wider
tolerance within a pixel of the model's edges was tried in the objective and
dropped: outputs got longer, and no more targets were solved.

## Experiment: learned motif proposals

The step rule takes a motif when it lowers J right after the step, which is
myopic. To label proposals by their outcome instead, `bench/proposals.py`
generates 90 scenes from the families (fresh seeds, 15 per family). It runs
the search once with every motif declined. For each step that offered
motifs, it reruns the search accepting one of them there and nothing
elsewhere. A proposal is good if the final J, after refining and the
clean-up, is lower.

Of 989 proposals, 140 (14%) lowered the final J. The step rule and the
outcome often disagree: a proposal that cut the step's J by 35,000 on a
stripes scene left the final J 345 higher. By kind, nested rings helped 40%
of the time and turns about a detected center 22%, with large average gains.
Seeded mirrors helped 21% and hurt 34%. Seeded copies never changed the
outcome.

A gradient-boosted classifier on 15 features of the proposal and the step
(its kind, size, pixels fixed, the step's J change, the stack's size, the
palette's size) was tested leave one family out, which asks whether what it
learns transfers to an unseen structure:

| held-out family | proposals | good | learned: accuracy | step rule: accuracy | learned: precision | step rule: precision |
|---|---|---|---|---|---|---|
| mirror | 111 | 3 | 0.96 | 0.69 | – | 0.03 |
| petals | 256 | 94 | 0.65 | 0.58 | 0.60 | 0.44 |
| repeat | 207 | 0 | 0.87 | 0.46 | – | 0.00 |
| rings | 204 | 22 | 0.86 | 0.77 | – | 0.25 |
| scatter | 112 | 21 | 0.80 | 0.80 | 0.40 | 0.43 |
| stripes | 99 | 0 | 0.98 | 0.96 | – | 0.00 |

Its accuracy is mostly that of saying no. When a family is held out, it
almost never accepts a proposal there (– means it accepted none), so it does
not transfer to an unseen structure. On rings, the step rule finds the good
nests, and the filter, which has seen nests only in the other families,
rejects them. Used in the compiler (trained on all six families), it solved
fewer development-split targets than the step rule, at the same CPU time
(first table above). The filter is not used. What would help is the oracle itself:
labels showed a few proposals with very large effects, so a policy has to
get rare cases right, not the average.

## What doesn't work yet

- **Search order.** Re-search fixes some greedy mistakes, but a lotus of
  three overlapping leaves is still drawn with polygons where a golfer uses
  three rotated leaves, and two circles stacked on an oval become one tall
  rounded box plus patches (the box fixes more pixels than either circle).
  Two fixes were tried and dropped: proposing one shape over all of a
  color's regions (the oval under the circles), and splitting regions at
  narrow necks (into the two circles). Together they raised the total J by
  3% and cost 9 targets their lead over the human code: the greedy search
  takes the big shapes early and then patches around them.
- **More primitives:** gradients on shapes, borders, text.
- **Antialiasing:** a linear ramp only approximates how Chromium smooths a
  rotated edge, so striped flags still carry a few hundred wrong pixels.

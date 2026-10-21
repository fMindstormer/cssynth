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
length-aware mode wins on 53 of 66 targets, but the other mode still wins on
some: a cheap shape now can leave more to draw later. Running both lowered
the total J by 2.5% and the characters by 670. Twice the searches cost
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
shorter than the (minified, not golfed) human solution on 56, and 23,823
characters in total against 35,532, with 65 of 66 at a 99%+ pixel match in
Chromium. See the [README](../README.md#results) and the
[results page](https://fmindstormer.github.io/cssynth/) for every target and
the generated code.

## What each part buys

Switching off one technique at a time and recompiling all 66 targets
(scores from cssynth's own rasterizer; the parts overlap, so the rows don't
add up):

| Switched off | Total J | Characters | Shorter than human |
|---|---|---|---|
| nothing (full compiler) | 64,477 | 23,823 | 56 / 66 |
| Re-search of the best result | 68,264 (+5.9%) | 24,958 (+1,135) | 55 / 66 |
| Polygons traced from outlines | 68,102 (+5.6%) | 26,426 (+2,603) | 51 / 66 |
| Insertion at any depth (shapes go on top) | 67,931 (+5.4%) | 25,079 (+1,256) | 52 / 66 |
| Gradient backgrounds | 67,100 (+4.1%) | 24,620 (+797) | 54 / 66 |
| Length-aware shape choice (by pixels only) | 66,097 (+2.5%) | 24,493 (+670) | 53 / 66 |
| Length-aware clean-up | 65,528 (+1.6%) | 24,954 (+1,131) | 53 / 66 |
| Box-shadows | 65,314 (+1.3%) | 24,660 (+837) | 56 / 66 |
| Soft gradient stops | 65,135 (+1.0%) | 24,261 (+438) | 55 / 66 |
| Splitting regions that touch at corners | 64,883 (+0.6%) | 24,205 (+382) | 55 / 66 |
| Per-tag rules (`<i>`, `<u>`, `<s>`) | 64,880 (+0.6%) | 24,210 (+387) | 55 / 66 |
| `clip-path` reuse for copies and mirrors | 64,744 (+0.4%) | 24,098 (+275) | 54 / 66 |
| Exact (CP-SAT) shadow grouping, greedy kept | 64,601 (+0.2%) | 23,941 (+118) | 56 / 66 |

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

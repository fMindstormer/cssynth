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

Hill climbing evaluates hundreds of thousands of candidate shapes, so the
gain function is the hot loop. Two exact shortcuts:

- **Boxes** use a summed-area table of (fixable − breakable) pixels, so a
  plain box costs four lookups. Rounded corners subtract what each corner
  cuts away; CSS scales radii so adjacent corners never overlap, so the cuts
  lie in disjoint corner blocks and each is evaluated with the same
  floating-point expression as the full rasterizer, giving bit-identical
  results.
- **Polygon vertex moves** only change pixels near the moved vertex's two
  edges. The even-odd test of a pixel depends only on the edges, not on
  which other pixels are sampled, so testing the old and new polygon on that
  window alone gives the exact change in gain.

Both were checked against the full rasterizer, on 20,000 random boxes and
hundreds of random polygon moves.

### Variants and shared searches

The greedy search has a few knobs: how many pixels a shape must fix
(`min_gain`), whether bounding boxes are always climbed, flat or gradient
base, whether outline polygons are proposed. Eight settings run per image
and the lowest J wins. A run with a higher `min_gain` mostly retraces the
lower one and stops where nothing fixes enough pixels, so one search reports
both: on the benchmark this gives exactly the same results as running them
separately.

### Re-search

The greedy search commits to shapes in the order they first help. An early
polygon can take a region that a shorter primitive would have drawn, and
everything around it is then fitted to that choice. After the variants, the
best result goes through a small large-neighborhood search: remove one
polygon (and forbid polygons of its color), or every shape of one color
(with or without polygons), refill the gap with the greedy search from the
remaining stack, refine, simplify, and keep the result if J drops.

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

See the [README](../README.md#results) and the
[results page](https://fmindstormer.github.io/cssynth/) for the numbers,
every target, and the generated code.

## What doesn't work yet

- **Search order.** Re-search fixes some greedy mistakes, but a lotus of
  three overlapping leaves is still drawn with polygons where a golfer uses
  three rotated leaves.
- **More primitives:** `repeating-*-gradient`, gradients on shapes,
  borders, text.
- **Antialiasing:** a linear ramp only approximates how Chromium smooths a
  rotated edge, so striped flags still carry a few hundred wrong pixels.

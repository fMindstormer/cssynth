# cssc

A compiler from images to short HTML/CSS, aimed at CSSBattle targets: flat
400×300 pictures you redraw in as few characters as possible.

```sh
pip install numpy scipy pillow ortools
python -m cssc target.png              # prints the code, length on stderr
python -m cssc -v target.png           # also logs the search
python -m cssc --rho 2 target.png      # golf harder (see "Objective")
```

## Objective

Everything is scored by one number:

    J = characters + wrong pixels / rho

`rho` is how many wrong pixels the compiler accepts to save one character
(default 0.5). CSSBattle tells players to reach a 100% match before cutting
characters, so the default is cautious; `bench/tradeoff.py` measures what
larger values buy.

## Pipeline

1. **Palette** (`search.extract_palette`): flat colors with at least 40
   pixels. A color lying between two others counts as antialiasing only when
   its pixels form thin lines (nothing survives one erosion); a solid region
   of such a color is a real fill, e.g. a semi-transparent shape.
2. **Base layer**: a flat background color, or for striped pictures a
   hard-stop `linear-gradient` (`search.fit_gradient`). Every pixel center is
   projected onto the gradient line for each angle (1° scan, then refined);
   dynamic programming over 1-px bins then chooses band boundaries minimizing
   wrong pixels + a penalty per stop. Chromium does not antialias hard stops,
   so the model samples pixel centers only (matches Chromium to 2–3 pixels).
3. **Layered greedy search** (`search.greedy`): repeatedly add the shape that
   fixes the most wrong pixels. Candidates come from connected regions of wrong
   pixels: boxes, ellipses, boxes with various corner radii, a 45° diamond, a
   bar along the region's principal axis, and triangles, quads and pentagons
   from its convex hull (emitted as `clip-path:polygon`). The plain bounding
   box of each color's largest regions is always climbed too: from there a
   climb peels a compound region (a cross, an I-beam) down to its biggest bar.
   Each candidate is hill-climbed on its edges, radii, rotation or vertices.
   A shape may be inserted **at any depth** in the stack: for each depth the
   gain is computed against the canvas below it and only the pixels that the
   shapes above leave visible. This is what lets it build rings and nested
   figures.
4. **Refine** (`search.refine`): merge two touching same-color shapes into one
   when that costs fewer than `min_gain` pixels; re-fit each shape against its
   final surroundings; delete shapes that no longer fix enough pixels; snap
   coordinates to multiples of 5/10 when it changes nothing.
5. **Simplify for length** (`simplify.simplify`): local moves scored by J,
   with code length measured by running the real code generator: drop a
   shape; snap two near-equal shapes to identical (or uniformly grown)
   geometry so they can become box-shadows of one another or share CSS, then
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
     last rule (the parser closes both at end of input).
7. **Choose**: six search settings run per image (`__main__.VARIANTS`); each
   result is simplified and scored by J, and the lowest J wins.

## Benchmark

The case list with lengths (`bench/cases.json`), our outputs (`bench/out/`)
and scores (`bench/results.json`) are included, plus the first version's
results (`bench/results_v1.json`, `bench/out_v1/`) for comparison. The 31
targets from `OmPreetham/cssbattle` (MIT) are included with their code; the
35 from `Kushalshakya/CSSBattle`, which has no license, are downloaded and
rendered by `bench/fetch.py` (see THIRD_PARTY.md). To re-run:

```sh
cd bench && npm install && cd ..    # @sparticuz/chromium + puppeteer-core
python bench/fetch.py               # download and render the remaining targets
python bench/run.py                 # compile all, render in Chromium, score
python bench/reemit.py              # re-run only code generation on saved shapes
python bench/tradeoff.py            # characters vs match for several rho
```

Targets are Chromium renders of public human solutions from
`Kushalshakya/CSSBattle` and `OmPreetham/cssbattle`, so each target is exactly
reproducible. Match = share of pixels within 8/255 per channel of the target,
measured on Chromium's render of the generated code. Human lengths are those
readable solutions minified, not golfed; top CSSBattle scores are far shorter.

## Open problems

- **Search for structure.** The greedy still adds whatever fixes the most
  pixels next; length only enters afterwards. Scoring partial programs by
  their final code length during the search (e.g. beam search over J) is the
  next step.
- **Antialiasing.** Hard gradient stops and some rotated edges differ from the
  target's antialiasing by a pixel band, which caps the match on a few flags.
- **More primitives.** Borders, repeated patterns via `repeating-*-gradient`,
  gradients on boxes (not only the background), text.

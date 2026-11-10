"""Re-search parts of a finished stack (a small large-neighborhood search).

The greedy search commits to shapes in the order they first help, so an early
polygon can take a region that a shorter primitive (a leaf, a rounded box)
would have drawn, and the shapes around it are then fitted to that choice.
This pass takes the best result, removes part of it, refills the gap with the
greedy search, refines and simplifies, and keeps the new stack when the
objective J (characters + wrong pixels / rho) goes down. Neighborhoods, cheap
ones first:

  * one polygon, refilled without polygons for its color
  * every shape of one color, refilled as before
  * every shape of one color, refilled without polygons for that color
  * every shape of one color whose region falls into parts (two circles
    stacked, a cloud of discs), redrawn as one shape per part and refilled:
    the greedy search takes the shape over the whole region, because it
    fixes more pixels at that step than any one part, and patches the rest

Each is tried once, in a single pass that continues from the improved stack.
Every refill is finished (refined, simplified, emitted) before it is compared,
so a choice that loses its step can win on the whole program.
"""

from __future__ import annotations

import numpy as np
from scipy import ndimage

from .search import add_parts, greedy, parts, refine
from .shapes import Gradient
from .simplify import simplify

SCREEN = 1.3        # refills scoring worse than this times the best skip simplify
PARTS = True        # redraw colors whose regions fall into parts (see split_colors)


def _colors(pal, bg):
    if isinstance(bg, Gradient):
        return list(range(len(pal)))
    return [c for c in range(len(pal)) if c != bg] + [bg]


def neighborhoods(shapes, split=None):
    """(key, shapes kept, colors to draw without polygons, part masks to draw
    first or None, description). split: {color: part masks} (see split_colors)."""
    for i, s in enumerate(shapes):
        if s.poly:
            yield ("polygon", s.poly), shapes[:i] + shapes[i + 1:], (s.color,), None, f"polygon {i} without polygons"
    colors = sorted({s.color for s in shapes})
    for c in colors:
        yield ("color", c), [s for s in shapes if s.color != c], (), None, f"color {c}"
    for c in colors:
        if any(s.poly for s in shapes if s.color == c):
            yield (("color", c, "no polygons"), [s for s in shapes if s.color != c], (c,), None,
                   f"color {c} without polygons")
    for (c, whole), masks in (split or {}).items():
        yield (("parts", c, whole), [s for s in shapes if s.color != c], (), masks,
               f"color {c} in {len(masks)} {'whole ' if whole else ''}parts")


def split_colors(T, colors):
    """{(color, whole): masks of the parts of its regions} for the colors
    with a region that falls into parts (see search.parts), both ways."""
    out = {}
    for c in colors:
        lab, n = ndimage.label(T == c, structure=np.ones((3, 3)))
        for whole in (False, True):
            masks = [m for i in range(1, n + 1) for m in parts(lab == i, whole)]
            if masks:
                out[c, whole] = masks
    return out


def improve(score, pal, bg, T, shapes, rho, min_gain, per_color, bbox_starts, outlines,
            by_length=True, motifs=True, log=None):
    """score(shapes) -> J of the finished code. by_length: refill choosing
    shapes by length as well as pixels (see search.greedy); motifs: propose
    motifs while refilling. Returns the improved stack."""
    best, best_J = shapes, score(shapes)
    split = split_colors(T, [c for c in _colors(pal, bg) if c != bg]) if PARTS else {}
    tried = set()
    while True:
        nb = next((nb for nb in neighborhoods(best, split) if nb[0] not in tried), None)
        if nb is None:
            return best
        key, kept, no_polygons, seed, what = nb
        tried.add(key)
        if seed is not None:
            kept = add_parts(T, bg, kept, key[1], seed, min_gain)
        stack = greedy(T, bg, _colors(pal, bg), min_gain=min_gain, per_color=per_color,
                       bbox_starts=bbox_starts, outlines=outlines, start=kept,
                       no_polygons=no_polygons, pal=pal, rho=rho if by_length else None, motifs=motifs)[min_gain]
        stack = refine(T, bg, stack, min_gain=min_gain)
        if score(stack) > SCREEN * best_J:
            continue
        stack = simplify(T, bg, pal, stack, rho=rho)
        J = score(stack)
        if J < best_J - 1e-9:
            if log:
                log(f"  re-search {what}: J {best_J:.1f} -> {J:.1f}")
            best, best_J = stack, J

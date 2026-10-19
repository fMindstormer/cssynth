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

Each is tried once, in a single pass that continues from the improved stack.
"""

from __future__ import annotations

from .search import greedy, refine
from .shapes import Gradient
from .simplify import simplify

SCREEN = 1.3        # refills scoring worse than this times the best skip simplify


def _colors(pal, bg):
    if isinstance(bg, Gradient):
        return list(range(len(pal)))
    return [c for c in range(len(pal)) if c != bg] + [bg]


def neighborhoods(shapes):
    """(key, shapes kept, colors to draw without polygons, description)."""
    for i, s in enumerate(shapes):
        if s.poly:
            yield ("polygon", s.poly), shapes[:i] + shapes[i + 1:], (s.color,), f"polygon {i} without polygons"
    colors = sorted({s.color for s in shapes})
    for c in colors:
        yield ("color", c), [s for s in shapes if s.color != c], (), f"color {c}"
    for c in colors:
        if any(s.poly for s in shapes if s.color == c):
            yield (("color", c, "no polygons"), [s for s in shapes if s.color != c], (c,),
                   f"color {c} without polygons")


def improve(score, pal, bg, T, shapes, rho, min_gain, per_color, bbox_starts, outlines, log=None):
    """score(shapes) -> J of the finished code. Returns the improved stack."""
    best, best_J = shapes, score(shapes)
    tried = set()
    while True:
        nb = next((nb for nb in neighborhoods(best) if nb[0] not in tried), None)
        if nb is None:
            return best
        key, kept, no_polygons, what = nb
        tried.add(key)
        stack = greedy(T, bg, _colors(pal, bg), min_gain=min_gain, per_color=per_color,
                       bbox_starts=bbox_starts, outlines=outlines, start=kept,
                       no_polygons=no_polygons)[min_gain]
        stack = refine(T, bg, stack, min_gain=min_gain)
        if score(stack) > SCREEN * best_J:
            continue
        stack = simplify(T, bg, pal, stack, rho=rho)
        J = score(stack)
        if J < best_J - 1e-9:
            if log:
                log(f"  re-search {what}: J {best_J:.1f} -> {J:.1f}")
            best, best_J = stack, J

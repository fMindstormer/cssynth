"""Length-aware clean-up of a shape stack.

The search maximizes pixels fixed; this phase minimizes what CSSBattle
actually scores: code length, with wrong pixels as a penalty,

    J = characters + wrong_pixels / rho

where rho is how many wrong pixels we accept to save one character. Moves:

  * drop a shape
  * harmonize two near-equal shapes (same size, or sizes differing by the
    same amount in both directions) so they can become box-shadows of one
    another or share CSS, also at different angles, and polygons to exact
    copies or mirror images of one another (sharing a clip-path); the
    changed shape is then re-positioned
  * drop a polygon vertex (re-fitting the rest), since the search may pick a
    many-vertex polygon for a few pixels' gain
  * make an odd width or height even, so `padding` can size the box

Each move is kept only if J goes down. Code length is measured by running the
real code generator (with the fast greedy grouping), not estimated.
"""

from __future__ import annotations

import numpy as np

from .codegen import emit
from .search import _masks, gain, hill_climb
from .shapes import H, Shape, W, base_labels, coverage

REFIT_DROPS = 2


class Scorer:
    def __init__(self, T, bg, palette, rho):
        self.T, self.bg, self.pal, self.rho = T, bg, palette, rho
        self.base = base_labels(bg)
        self._masks = {}
        self._ov = {}

    def mask(self, s: Shape) -> np.ndarray:
        k = repr(s)
        if k not in self._masks:
            m = np.zeros((H, W), dtype=bool)
            x0, y0, c = coverage(s)
            if c is not None:
                m[y0:y0 + c.shape[0], x0:x0 + c.shape[1]] = c
            self._masks[k] = m
        return self._masks[k]

    def render(self, shapes) -> np.ndarray:
        canvas = self.base.copy()
        for s in shapes:
            canvas[self.mask(s)] = s.color
        return canvas

    def error(self, shapes) -> int:
        return int((self.render(shapes) != self.T).sum())

    def edges(self, shapes) -> set:
        out = set()
        for i in range(len(shapes)):
            for j in range(i + 1, len(shapes)):
                a, b = shapes[i], shapes[j]
                if a.color == b.color:
                    continue
                k = (repr(a), repr(b))
                if k not in self._ov:
                    self._ov[k] = bool((self.mask(a) & self.mask(b)).any())
                if self._ov[k]:
                    out.add((i, j))
        return out

    def chars(self, shapes) -> int:
        code, _ = emit(self.pal, self.bg, shapes, grouping="greedy", edges=self.edges(shapes))
        return len(code)

    def J(self, shapes) -> float:
        return self.chars(shapes) + self.error(shapes) / self.rho


def _box(s: Shape) -> bool:
    return not s.rot and not s.poly


def _recenter(s: Shape, w, h) -> Shape:
    cx, cy = s.x + s.w / 2, s.y + s.h / 2
    return s.copy(x=round(cx - w / 2), y=round(cy - h / 2), w=w, h=h)


def _harmonized(a: Shape, b: Shape, tol: int):
    """Versions of b changed to be shadow-compatible with a; for turned
    shapes, to share a's size and corners (and so a rule) at b's angle; for
    polygons, to be a copy or mirror of a in b's place (sharing a clip-path)."""
    if a.poly and b.poly:
        if (len(a.poly) == len(b.poly) and a.color == b.color
                and abs(a.w - b.w) <= tol and abs(a.h - b.h) <= tol):
            for fx in (False, True):
                for fy in (False, True):
                    f = a.flipped(fx, fy)
                    f = f.moved(round(b.x + b.w / 2 - f.x - f.w / 2), round(b.y + b.h / 2 - f.y - f.h / 2))
                    if f.poly != b.poly and _near_polygon(f.poly, b.poly, tol):
                        yield f
        return
    if a.poly or b.poly or a.ell != b.ell:
        return
    if a.rot or b.rot:
        if (abs(a.w - b.w) <= tol and abs(a.h - b.h) <= tol and (a.w, a.h, a.radii) != (b.w, b.h, b.radii)
                and (a.ell or all(abs(p - q) <= tol for p, q in zip(a.radii, b.radii)))):
            yield _recenter(b, a.w, a.h).copy(radii=a.radii)
        return
    if not a.ell and any(abs(p - q) > tol for p, q in zip(a.radii, b.radii)):
        return
    same = (abs(a.w - b.w) <= tol and abs(a.h - b.h) <= tol)
    if same and (a.w, a.h, a.radii) != (b.w, b.h, b.radii):
        yield _recenter(b, a.w, a.h).copy(radii=a.radii)
        yield b.copy(w=a.w, h=a.h, radii=a.radii)
    # concentric copies: grown by the same amount in both directions
    if (a.ell or not any(a.radii)) and (b.ell or not any(b.radii)):
        d = (b.w - a.w) - (b.h - a.h)
        if d and abs(d) <= tol:
            yield _recenter(b, b.w, b.h + d)
            yield _recenter(b, b.w - d, b.h)


def _near_polygon(p, q, tol) -> bool:
    """Every vertex within tol of the other's, in the same cyclic order
    (either direction)."""
    n = len(p)
    for qq in (q, q[::-1]):
        for k in range(n):
            if all(abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol
                   for a, b in zip(p, qq[k:] + qq[:k])):
                return True
    return False


def _even(s: Shape):
    if not _box(s):
        return
    if s.w % 2:
        yield s.copy(w=s.w + 1)
        yield s.copy(x=s.x - 1, w=s.w + 1)
        yield s.copy(w=s.w - 1)
    if s.h % 2:
        yield s.copy(h=s.h + 1)
        yield s.copy(y=s.y - 1, h=s.h + 1)
        yield s.copy(h=s.h - 1)


def _nudge(sc: Scorer, shapes, i, s: Shape) -> Shape:
    """Re-position shape i (size fixed) against its final surroundings."""
    below = sc.render(shapes[:i])
    above = np.zeros((H, W), dtype=bool)
    for t in shapes[i + 1:]:
        above |= sc.mask(t)
    A, B = _masks(sc.T, below, s.color, ~above)
    best, bg = s, gain(s, A, B)
    improved = True
    while improved:
        improved = False
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            c = best.moved(dx, dy)
            g = gain(c, A, B)
            if g > bg:
                best, bg, improved = c, g, True
    return best


def _refit(sc: Scorer, shapes, i, s: Shape) -> Shape:
    """Hill-climb shape i against its final surroundings."""
    below = sc.render(shapes[:i])
    above = np.zeros((H, W), dtype=bool)
    for t in shapes[i + 1:]:
        above |= sc.mask(t)
    A, B = _masks(sc.T, below, s.color, ~above)
    return hill_climb(s, A, B, steps=(4, 2, 1))[0]


def _fewer_vertices(s: Shape):
    """s with one polygon vertex removed, for each vertex."""
    if not s.poly or len(s.poly) <= 3:
        return
    for i in range(len(s.poly)):
        yield Shape.polygon(s.poly[:i] + s.poly[i + 1:], s.color)


def simplify(T, bg, palette, shapes, rho=2.0, tol=4, passes=3, log=None):
    sc = Scorer(T, bg, palette, rho)
    cur = list(shapes)
    J = sc.J(cur)
    for _ in range(passes):
        improved = False
        # drop shapes
        for i in reversed(range(len(cur))):
            trial = cur[:i] + cur[i + 1:]
            j = sc.J(trial)
            if j < J - 1e-9:
                if log:
                    log(f"  drop {cur[i]}: J {J:.1f} -> {j:.1f}")
                cur, J, improved = trial, j, True
        # harmonize pairs
        for i in range(len(cur)):
            for k in range(len(cur)):
                if i == k or i >= len(cur) or k >= len(cur):
                    continue
                for b2 in _harmonized(cur[i], cur[k], tol):
                    b2 = _nudge(sc, cur, k, b2)
                    trial = cur[:k] + [b2] + cur[k + 1:]
                    j = sc.J(trial)
                    if j < J - 1e-9:
                        if log:
                            log(f"  harmonize {cur[k]} with {cur[i]}: J {J:.1f} -> {j:.1f}")
                        cur, J, improved = trial, j, True
                        break
        # drop polygon vertices, one at a time, re-fitting what remains; only
        # the drops that look best before re-fitting are re-fitted
        for i in range(len(cur)):
            while True:
                best = None
                drops = sorted(_fewer_vertices(cur[i]), key=lambda s2: sc.J(cur[:i] + [s2] + cur[i + 1:]))
                for s2 in drops[:REFIT_DROPS]:
                    trial = cur[:i] + [_refit(sc, cur, i, s2)] + cur[i + 1:]
                    j = sc.J(trial)
                    if j < J - 1e-9 and (best is None or j < best[0]):
                        best = (j, trial)
                if best is None:
                    break
                if log:
                    log(f"  drop a vertex of {cur[i]}: J {J:.1f} -> {best[0]:.1f}")
                J, cur = best
                improved = True
        # even sizes
        for i in range(len(cur)):
            for s2 in _even(cur[i]):
                trial = cur[:i] + [s2] + cur[i + 1:]
                j = sc.J(trial)
                if j < J - 1e-9:
                    cur, J, improved = trial, j, True
                    break
        if not improved:
            break
    return cur

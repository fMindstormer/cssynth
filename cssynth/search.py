"""Decompose a flat-color target image into a stack of CSS-box shapes.

Pipeline:
  1. palette: find the flat colors, ignoring antialiasing blends
  2. greedy: repeatedly add the shape (on top) that fixes the most pixels,
     proposing candidates from connected regions of still-wrong pixels and
     refining each by hill climbing its edges, corner radii and rotation
  3. refine: re-fit every shape with everything else fixed, delete shapes that
     no longer pay for themselves, snap coordinates to round numbers
"""

from __future__ import annotations

import functools
import math

import numpy as np
from scipy import ndimage

from . import codegen, motifs
from .shapes import Gradient, H, Shape, W, base_labels, coverage, gradient_rgb, render_labels

MIN_COLOR_PX = 40
SAME_COLOR = 4          # max channel difference within which two colors are one
MIN_GAIN = 25          # pixels a shape must fix to be worth its characters
INSERT_ANYWHERE = True  # new shapes may go at any depth (False: on top only, for comparison)
TOP_STARTS = 10         # starts climbed per step, best first (plus a few per color)


# --------------------------------------------------------------------------
# Palette
# --------------------------------------------------------------------------

def extract_palette(img: np.ndarray):
    flat = img.reshape(-1, 3).astype(np.int32)
    keys = (flat[:, 0] << 16) | (flat[:, 1] << 8) | flat[:, 2]
    uniq, counts = np.unique(keys, return_counts=True)
    order = np.argsort(-counts)
    main: list[np.ndarray] = []
    keys2d = keys.reshape(img.shape[:2])
    for k, n in zip(uniq[order], counts[order]):
        if n < MIN_COLOR_PX:
            break
        c = np.array([(k >> 16) & 255, (k >> 8) & 255, k & 255], dtype=float)
        # A color a shade off another is the same fill (browsers paint turned
        # elements a level or two off); within tolerance either draws both.
        if main and np.abs(np.array(main) - c).max(1).min() <= SAME_COLOR:
            continue
        # A color between two others is antialiasing only if it forms thin
        # lines; a solid region of it is a real (often semi-transparent) fill.
        if _is_blend(c, main) and ndimage.binary_erosion(keys2d == k).sum() < MIN_COLOR_PX:
            continue
        main.append(c)
    if not main:
        main.append(flat[0].astype(float))
    pal = np.array(main)
    d = ((flat[:, None, :] - pal[None, :, :]) ** 2).sum(-1)
    labels = d.argmin(1).reshape(img.shape[:2]).astype(np.int16)
    return pal.astype(int), labels


def _is_blend(c, main, tol=7.0):
    for i in range(len(main)):
        for j in range(i + 1, len(main)):
            a, b = main[i], main[j]
            ab = b - a
            denom = float(ab @ ab)
            if denom == 0:
                continue
            t = float((c - a) @ ab) / denom
            if 0.04 < t < 0.96 and np.linalg.norm(a + t * ab - c) < tol:
                return True
    return False


def background(labels: np.ndarray) -> int:
    border = np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])
    return int(np.bincount(border).argmax())


# --------------------------------------------------------------------------
# Gradient base layer
# --------------------------------------------------------------------------

STOP_PENALTY = 150      # pixels a gradient band must explain to earn its stop
MAX_BANDS = 8


def _bin_counts(T, K, angle):
    g = Gradient(angle, ())
    p = g.positions()
    nb = int(math.ceil(g.length())) + 1
    b = np.clip(np.floor(p).astype(np.int64), 0, nb - 1)
    return np.bincount((b * K + T).ravel(), minlength=nb * K).reshape(nb, K)


def _segment(counts, max_bands=MAX_BANDS, penalty=STOP_PENALTY):
    """Split the bins into bands of one color each, minimizing mismatched
    pixels + penalty per band (dynamic programming over band ends)."""
    nb, K = counts.shape
    S = np.vstack([np.zeros((1, K)), np.cumsum(counts, axis=0)])        # prefix sums
    tot = S.sum(1)
    INF = float("inf")
    D = np.full((max_bands + 1, nb + 1), INF)
    arg = np.zeros((max_bands + 1, nb + 1), dtype=np.int64)
    D[0, 0] = 0.0
    for m in range(1, max_bands + 1):
        for j in range(1, nb + 1):
            seg = S[j][None, :] - S[:j]                                    # (j, K)
            cost = (tot[j] - tot[:j]) - seg.max(1) + D[m - 1, :j]
            i = int(cost.argmin())
            D[m, j], arg[m, j] = cost[i], i
    m_best = int(np.argmin([D[m, nb] + penalty * m for m in range(1, max_bands + 1)])) + 1
    bands, j = [], nb
    for m in range(m_best, 0, -1):
        i = arg[m, j]
        bands.append((i, j, int((S[j] - S[i]).argmax())))
        j = i
    bands.reverse()
    merged = []
    for i, j, c in bands:                       # neighbors of one color: one band
        if merged and merged[-1][2] == c:
            merged[-1] = (merged[-1][0], j, c)
        else:
            merged.append((i, j, c))
    return float(D[m_best, nb]), merged


def fit_gradient(T, K):
    """Best hard-stop linear-gradient base layer, or None when bands don't
    explain the picture much better than a flat background."""
    flat_err = int((T != background(T)).sum())
    coarse = []
    for a in range(0, 180):
        c = _bin_counts(T, K, a)
        coarse.append((int(c.sum() - c.max(1).sum()), a))
    coarse.sort()
    angles = {a for _, a in coarse[:2]} | {90, 180}
    best = None
    for a0 in sorted(angles):
        cands = [a0] if a0 % 90 == 0 else [round(a0 + d / 4, 2) for d in range(-4, 5)]
        for a in cands:
            err, bands = _segment(_bin_counts(T, K, a))
            score = err + STOP_PENALTY * len(bands)
            if len(bands) >= 2 and (best is None or score < best[0]):
                best = (score, err, a, bands)
    if best is None or best[0] > 0.8 * flat_err:
        return None
    _, err, a, bands = best
    stops = tuple((c, float(j)) for i, j, c in bands)
    if a == 0:      # bottom-to-top: same picture as the default 180deg, reversed
        L = Gradient(0, ()).length()
        stops = tuple((c, float(L - i)) for i, j, c in reversed(bands))
        a = 180
    return Gradient(float(a), stops)


SOFT_WIDTHS = (0, 0.6, 0.8, 1, 1.2, 1.4, 1.6, 2)
SOFT_PAYS = 12          # wrong pixels a soft boundary must save (its ~6 characters)


def soften(g: Gradient, img: np.ndarray, pal) -> Gradient:
    """Move each boundary by up to 1.5px in 0.1px steps and give it a ramp,
    to match the antialiased edges of the target (a gradient line drawn by a
    rotated box, say) instead of Chromium's hard, unantialiased stop."""
    P = g.positions()
    pal = np.asarray(pal, dtype=float)
    target = img.astype(int)
    stops, soft = list(g.stops), [0.0] * (len(g.stops) - 1)
    for i in range(len(soft)):
        e0 = stops[i][1]
        near = np.abs(P - e0) < 4            # only these pixels can change
        pos, tgt = P[near], target[near]

        def wrong(e, w):
            trial = Gradient(g.angle, tuple(stops[:i] + [(stops[i][0], e)] + stops[i + 1:]),
                             tuple(soft[:i] + [w] + soft[i + 1:]))
            got = np.rint(gradient_rgb(trial, pal, pos)).astype(int)
            return int((np.abs(got - tgt).max(-1) > 8).sum())

        hard = wrong(e0, 0)
        best = min((wrong(round(e0 + d / 10, 1), w), w, round(e0 + d / 10, 1))
                   for d in range(-15, 16) for w in SOFT_WIDTHS[1:])
        if best[0] < hard - SOFT_PAYS:
            stops[i], soft[i] = (stops[i][0], best[2]), best[1]
    if not any(soft):
        return g
    return Gradient(g.angle, tuple(stops), tuple(soft))


# --------------------------------------------------------------------------
# Gain and hill climbing
# --------------------------------------------------------------------------

def gain(s: Shape, A: np.ndarray, B: np.ndarray, sums=None) -> int:
    """Pixels fixed minus pixels broken by painting s on top.
    A: target is s.color and currently wrong.  B: currently right and not s.color.
    sums: tables of A - B (see area_sums), which make the gain a few lookups."""
    if sums is not None:
        if not (s.rot % 360 or s.ell or s.poly or any(s.radii)):
            return _rect_gain(s, sums)
        runs = _runs((s.x, s.y, s.w, s.h, s.radii, s.ell, s.rot, s.poly))
        if runs is None:
            return -10**9
        starts, ends = runs
        return int(sums.flat[ends].sum() - sums.flat[starts].sum())
    x0, y0, m = coverage(s)
    if m is None:
        return -10**9
    h, w = m.shape
    return (np.count_nonzero(A[y0:y0 + h, x0:x0 + w] & m)
            - np.count_nonzero(B[y0:y0 + h, x0:x0 + w] & m))


class Sums:
    """Tables of D = A - B for fast gains: its per-row running sums
    (rows[j, i] = sum of row j over columns < i; flat is the same, raveled)
    and its summed-area table (area[j, i] = sum over rows < j, columns < i)."""

    def __init__(self, A, B):
        self.rows = np.zeros((H, W + 1), dtype=np.int32)
        np.cumsum(A.astype(np.int32) - B, axis=1, out=self.rows[:, 1:])
        self.flat = self.rows.ravel()
        self.area = np.zeros((H + 1, W + 1), dtype=np.int32)
        self.area[1:] = self.rows.cumsum(0)


def area_sums(A, B) -> Sums:
    return Sums(A, B)


def _rect_gain(s: Shape, S: Sums) -> int:
    """gain() for a plain box: the sum over its rectangle from the table."""
    # pixel i is inside when its center i + 0.5 lies in [x, x + w]
    i0 = max(0, math.ceil(s.x - 0.5))
    i1 = min(W, math.floor(s.x + s.w - 0.5) + 1)
    j0 = max(0, math.ceil(s.y - 0.5))
    j1 = min(H, math.floor(s.y + s.h - 0.5) + 1)
    x0, y0, x1, y1 = s.bbox()
    if x1 <= x0 or y1 <= y0 or s.w <= 0 or s.h <= 0:
        return -10**9                       # as gain(): nothing on the canvas
    if i1 <= i0 or j1 <= j0:
        return 0
    T = S.area
    return int(T[j1, i1] - T[j0, i1] - T[j1, i0] + T[j0, i0])


@functools.lru_cache(maxsize=1 << 15)
def _runs(geometry):
    """The pixels of a shape (everything but its color) as runs along rows:
    flat indices into Sums.flat of where each run starts and ends, so a gain
    is two sums. The pixels are exactly coverage()'s, so gains are identical.
    Shapes recur across a search (each step re-climbs from much the same
    starts, against new pixels), so the runs are cached."""
    s = Shape(*geometry[:4], 0, *geometry[4:])
    x0, y0, x1, y1 = s.bbox()
    if x1 <= x0 or y1 <= y0 or s.w <= 0 or s.h <= 0:
        return None
    if s.poly:
        rows, a, b = _poly_runs(s, y0, y1)
    elif s.rot % 360:
        rows, a, b = _mask_runs(s)
    else:
        rows, a, b = _box_runs(s, x0, y0, x1, y1)
    keep = a < b
    flat = rows[keep] * (W + 1)
    return (flat + a[keep]).astype(np.int32), (flat + b[keep]).astype(np.int32)


_CENTERS = np.arange(max(W, H)) + 0.5
_SIGNS = ((-1, -1), (1, -1), (1, 1), (-1, 1))          # tl, tr, br, bl


def _box_runs(s: Shape, x0, y0, x1, y1):
    """An unrotated box: one run per pixel row, from its left side to its
    right, shortened by what the rounded corners cut away. A corner's cut in
    a row is the pixels nearest the box's side (the test in shapes._in_box
    grows monotonically outward), so a count per row places it. Every test
    is coverage()'s own arithmetic."""
    hw, hh = s.w / 2, s.h / 2
    cx, cy = s.x + hw, s.y + hh
    cols = x0 + np.flatnonzero(np.abs(_CENTERS[x0:x1] - cx) <= hw)
    rows = y0 + np.flatnonzero(np.abs(_CENTERS[y0:y1] - cy) <= hh)
    if not len(cols) or not len(rows):
        return _CENTERS[:0], _CENTERS[:0], _CENTERS[:0]
    i0, i1, j0, j1 = cols[0], cols[-1] + 1, rows[0], rows[-1] + 1
    start, end = np.full(j1 - j0, i0), np.full(j1 - j0, i1)
    for (rx, ry), (sx, sy) in zip(s.corner_radii(), _SIGNS):
        if rx <= 0 or ry <= 0:
            continue
        cu, cv = sx * (hw - rx), sy * (hh - ry)
        # the pixels this corner can cut: centers beyond the arc's center,
        # with a pixel to spare
        mi, mj = math.floor(cx + cu), math.floor(cy + cv)
        a0, a1 = (i0, min(i1, mi + 1)) if sx < 0 else (max(i0, mi - 1), i1)
        b0, b1 = (j0, min(j1, mj + 1)) if sy < 0 else (max(j0, mj - 1), j1)
        if a1 <= a0 or b1 <= b0:
            continue
        ou, ov = a0 + 0.5 - cx - cu, b0 + 0.5 - cy - cv
        if all((t * 64).is_integer() and abs(t) < 4096 for t in (cx, cy, cu, cv)):
            # every offset from the arc's center is then exact, so the cut
            # depends only on them, and a moved or resized box reuses it
            n = _corner_cut(rx, ry, sx, sy, ou, ov, a1 - a0, b1 - b0)
        else:
            u = (np.arange(a0, a1) + 0.5 - cx)[None, :] - cu
            v = (np.arange(b0, b1) + 0.5 - cy)[:, None] - cv
            n = _cut(u, v, rx, ry, sx, sy)
        if sx < 0:
            start[b0 - j0:b1 - j0] = np.maximum(start[b0 - j0:b1 - j0], a0 + n)
        else:
            end[b0 - j0:b1 - j0] = np.minimum(end[b0 - j0:b1 - j0], a1 - n)
    return np.arange(j0, j1), start, np.maximum(start, end)


def _cut(u, v, rx, ry, sx, sy):
    """Per row, the pixels a corner cuts: u, v are pixel centers' offsets
    from the arc's center, computed as in shapes._in_box."""
    du, dv = u / rx, v / ry
    return ((u * sx > 0) & (v * sy > 0) & (du * du + dv * dv > 1)).sum(1)


@functools.lru_cache(maxsize=1 << 14)
def _corner_cut(rx, ry, sx, sy, ou, ov, nu, nv):
    return _cut((np.arange(nu) + ou)[None, :], (np.arange(nv) + ov)[:, None], rx, ry, sx, sy)


def _poly_runs(s: Shape, y0, y1):
    """A polygon: in each pixel row it covers the spans between pairs of
    sorted edge crossings. The crossings use shapes._in_polygon's arithmetic
    and its "center left of the crossing" test."""
    P = np.asarray(s.poly, dtype=float)
    (xa, ya), (xb, yb) = P.T, np.roll(P, -1, 0).T
    keep = ya != yb
    xa, ya, xb, yb = xa[keep], ya[keep], xb[keep], yb[keep]
    Y = (np.arange(y0, y1) + 0.5)[:, None]
    crosses = (Y >= np.minimum(ya, yb)) & (Y < np.maximum(ya, yb))
    xint = np.where(crosses, xa + (Y - ya) * (xb - xa) / (yb - ya), np.inf)
    if xint.shape[1] % 2:                # pad to whole pairs; spans of two infs are empty
        xint = np.pad(xint, ((0, 0), (0, 1)), constant_values=np.inf)
    idx = np.searchsorted(_CENTERS[:W], np.sort(xint, axis=1), side="left")
    rows = np.repeat(np.arange(y0, y1), idx.shape[1] // 2)
    return rows, idx[:, 0::2].ravel(), idx[:, 1::2].ravel()


def _mask_runs(s: Shape):
    """A turned box, from coverage(). It is convex, so each row is one run;
    rows that are not (rounding at a tangent) fall back to scanning."""
    x0, y0, m = coverage(s)
    rows = np.flatnonzero(m.any(1))
    m = m[rows]
    a = m.argmax(1)
    b = m.shape[1] - m[:, ::-1].argmax(1)
    if (m.sum(1) == b - a).all():
        return rows + y0, a + x0, b + x0
    edges = np.diff(m.astype(np.int8), axis=1, prepend=0, append=0)
    r, a = np.nonzero(edges == 1)          # row-major, so starts and ends pair up
    _, b = np.nonzero(edges == -1)
    return rows[r] + y0, a + x0, b + x0


def _moves(s: Shape, step: int):
    if s.poly:
        pts = list(s.poly)
        for i in range(len(pts)):
            for dx, dy in ((step, 0), (-step, 0), (0, step), (0, -step)):
                q = pts.copy()
                q[i] = (q[i][0] + dx, q[i][1] + dy)
                yield Shape.polygon(q, s.color)
        for dx, dy in ((step, 0), (-step, 0), (0, step), (0, -step)):
            yield Shape.polygon([(a + dx, b + dy) for a, b in pts], s.color)
        return
    x0, y0, x1, y1 = s.x, s.y, s.x + s.w, s.y + s.h
    edge_sets = [(x0 - step, y0, x1, y1), (x0 + step, y0, x1, y1),
                 (x0, y0 - step, x1, y1), (x0, y0 + step, x1, y1),
                 (x0, y0, x1 - step, y1), (x0, y0, x1 + step, y1),
                 (x0, y0, x1, y1 - step), (x0, y0, x1, y1 + step),
                 (x0 - step, y0, x1 - step, y1), (x0 + step, y0, x1 + step, y1),
                 (x0, y0 - step, x1, y1 - step), (x0, y0 + step, x1, y1 + step)]
    for a, b, c, d in edge_sets:
        if c - a >= 1 and d - b >= 1:
            yield s.copy(x=a, y=b, w=c - a, h=d - b)
    if s.rot:
        # grow/shrink about the center keeps rotated shapes centered
        for dw in (-step, step):
            yield s.copy(x=s.x - dw / 2, y=s.y - dw / 2, w=s.w + dw, h=s.h + dw)
            if SCALE_MOVES and any(s.radii):
                # and its corners with it, which keeps a leaf a leaf
                yield s.copy(x=s.x - dw / 2, y=s.y - dw / 2, w=s.w + dw, h=s.h + dw,
                             radii=tuple(max(0, r + dw) if r else 0 for r in s.radii))
        for da in (-1, 1) if step <= 2 else ():
            yield s.copy(rot=s.rot + da)
    if not s.ell:
        for i in range(4):
            if s.radii[i] > 0 or step <= 4:
                r = list(s.radii)
                for dr in (-step, step):
                    r2 = r.copy()
                    r2[i] = max(0, r[i] + dr)
                    if r2 != r:
                        yield s.copy(radii=tuple(r2))


def hill_climb(s: Shape, A, B, steps=(16, 8, 4, 2, 1), sums=None) -> tuple[Shape, int]:
    """sums: area_sums(A, B), when the caller already has it."""
    if sums is None:
        sums = area_sums(A, B)
    seen = {}

    def score(c):
        k = (c.x, c.y, c.w, c.h, c.radii, c.ell, c.rot, c.poly)
        if k not in seen:
            seen[k] = gain(c, A, B, sums)
        return seen[k]

    best, bg = s, score(s)
    for step in steps:
        improved = True
        while improved:
            improved = False
            for cand in _moves(best, step):
                g = score(cand)
                if g > bg:
                    best, bg, improved = cand, g, True
    return best, bg


# --------------------------------------------------------------------------
# Candidates
# --------------------------------------------------------------------------

def candidates(color: int, comp: np.ndarray, x0: int, y0: int, outlines=False):
    """Shapes to try for one connected region (comp is its bool mask,
    positioned at x0, y0). outlines: also polygons fitted to its outline."""
    h, w = comp.shape
    x1, y1 = x0 + w, y0 + h
    m = min(w, h)
    yield Shape(x0, y0, w, h, color)
    yield Shape(x0, y0, w, h, color, ell=True)
    if w != h:
        yield Shape(x0, y0, w, h, color, radii=(m / 2,) * 4)
    for r in [(m, 0, 0, 0), (0, m, 0, 0), (0, 0, m, 0), (0, 0, 0, m),
              (m, 0, m, 0), (0, m, 0, m)]:
        yield Shape(x0, y0, w, h, color, radii=r)
    hw, hh = w / 2, h / 2
    for r in [(hw, hw, 0, 0), (0, 0, hw, hw), (hh, 0, 0, hh), (0, hh, hh, 0)]:
        yield Shape(x0, y0, w, h, color, radii=r)
    # a diamond: square rotated 45deg inscribed in the bbox
    side = (w + h) / 2 / math.sqrt(2)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    yield Shape(round(cx - side / 2), round(cy - side / 2), round(side), round(side), color, rot=45)
    # a bar along the region's principal axis
    ys, xs = np.nonzero(comp)
    if len(xs) >= 20:
        X, Y = xs + x0 + 0.5, ys + y0 + 0.5
        mx, my = X.mean(), Y.mean()
        cxx, cyy, cxy = ((X - mx) ** 2).mean(), ((Y - my) ** 2).mean(), ((X - mx) * (Y - my)).mean()
        t = 0.5 * math.atan2(2 * cxy, cxx - cyy)
        deg = round(math.degrees(t))
        u = (X - mx) * math.cos(t) + (Y - my) * math.sin(t)
        v = -(X - mx) * math.sin(t) + (Y - my) * math.cos(t)
        bw, bh = u.max() - u.min() + 1, v.max() - v.min() + 1
        ccx = mx + (u.max() + u.min()) / 2 * math.cos(t) - (v.max() + v.min()) / 2 * math.sin(t)
        ccy = my + (u.max() + u.min()) / 2 * math.sin(t) + (v.max() + v.min()) / 2 * math.cos(t)
        if deg % 90:
            bar = Shape(round(ccx - bw / 2), round(ccy - bh / 2), round(bw), round(bh), color, rot=deg)
            yield bar
            yield bar.copy(radii=(round(min(bw, bh) / 2),) * 4)
        # a leaf: a square rounded on two opposite corners, turned so its tips
        # lie on the axis (border-radius:100% 0 and a rotation)
        side = round(bw / math.sqrt(2))
        yield Shape(round(ccx - side / 2), round(ccy - side / 2), side, side, color,
                    radii=(side, 0, side, 0), rot=(deg + 45) % 180)
    # triangles and quads from the region's convex hull
    for k in (3, 4, 5):
        pts = hull_polygon(comp, x0, y0, k)
        if pts is not None:
            yield Shape.polygon(pts, color)
    # polygons from the region's own outline, which may be concave and have
    # more vertices than the hull fit (stars, arrows, notched squares)
    if not outlines:
        return
    outline = trace_outline(comp)
    if outline is not None:
        for k in CONTOUR_KS:
            pts = reduce_polygon(outline, k)
            if pts is not None:
                yield Shape.polygon([(a + x0, b + y0) for a, b in pts], color)


CONTOUR_KS = (4, 5, 6, 8, 10, 12)


def trace_outline(comp):
    """The outer boundary of a region (holes filled) as a list of pixel-corner
    vertices, clockwise on screen, with collinear points removed."""
    filled = np.pad(ndimage.binary_fill_holes(comp), 1)
    if filled.sum() < 3:
        return None
    # one directed edge per exposed pixel side, interior on the right
    nxt = {}
    ys, xs = np.nonzero(filled)
    for (dy, dx), (a, b) in (((-1, 0), ((0, 0), (1, 0))), ((0, 1), ((1, 0), (1, 1))),
                             ((1, 0), ((1, 1), (0, 1))), ((0, -1), ((0, 1), (0, 0)))):
        sel = ~filled[ys + dy, xs + dx]
        for x, y in zip(xs[sel] - 1, ys[sel] - 1):
            nxt.setdefault((x + a[0], y + a[1]), []).append((x + b[0], y + b[1]))
    # chain edges into loops; keep the one enclosing the most area
    best, best_area = None, 0
    while nxt:
        start = next(iter(nxt))
        loop, p = [start], start
        while True:
            outs = nxt[p]
            q = outs.pop()
            if not outs:
                del nxt[p]
            if q == start:
                break
            loop.append(q)
            p = q
            if p not in nxt:        # pinch point already consumed: give up on this loop
                break
        if len(loop) < 4:
            continue
        P = np.array(loop, dtype=float)
        area = abs(np.dot(P[:, 0], np.roll(P[:, 1], -1)) - np.dot(P[:, 1], np.roll(P[:, 0], -1))) / 2
        if area > best_area:
            best, best_area = loop, area
    if best is None:
        return None
    n = len(best)
    return [best[i] for i in range(n)
            if (best[i][0] - best[i - 1][0]) * (best[(i + 1) % n][1] - best[i][1])
            != (best[i][1] - best[i - 1][1]) * (best[(i + 1) % n][0] - best[i][0])]


def reduce_polygon(pts, k):
    """Visvalingam: repeatedly drop the vertex spanning the smallest triangle
    with its neighbors, down to k vertices."""
    P = np.array(pts, dtype=float)
    if len(P) < k:
        return None
    while len(P) > k:
        a, c = np.roll(P, 1, 0), np.roll(P, -1, 0)
        area = np.abs((P[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1])
                      - (c[:, 0] - a[:, 0]) * (P[:, 1] - a[:, 1]))
        P = np.delete(P, int(area.argmin()), 0)
    return [tuple(p) for p in P]


def hull_polygon(comp, x0, y0, k):
    from scipy.spatial import ConvexHull, QhullError
    edge = comp & ~ndimage.binary_erosion(comp)
    ys, xs = np.nonzero(edge)
    if len(xs) < 3:
        return None
    pts = np.concatenate([np.stack([xs + dx, ys + dy], 1) for dx in (0, 1) for dy in (0, 1)])
    try:
        hull = ConvexHull(pts)
    except QhullError:
        return None
    poly = [tuple(pts[i] + (x0, y0)) for i in hull.vertices]
    def tri_area(a, b, c):
        return abs((b[0] - a[0]) * (c[1] - a[1]) - (c[0] - a[0]) * (b[1] - a[1])) / 2
    while len(poly) > k:
        n = len(poly)
        i = min(range(n), key=lambda j: tri_area(poly[j - 1], poly[j], poly[(j + 1) % n]))
        poly.pop(i)
    return poly if len(poly) == k else None


def _masks(T, C, c, free=None):
    A = (T == c) & (C != c)
    B = (C == T) & (T != c)
    if free is not None:
        A &= free
        B &= free
    return A, B


# --------------------------------------------------------------------------
# Main search
# --------------------------------------------------------------------------

def _layers(T, bg, shapes):
    """For each insertion depth k: the canvas below it and the pixels that
    shapes above it leave visible."""
    n = len(shapes)
    covs = [coverage(s) for s in shapes]
    belows = [base_labels(bg)]
    for (x0, y0, m) in covs:
        c = belows[-1].copy()
        if m is not None:
            c[y0:y0 + m.shape[0], x0:x0 + m.shape[1]][m] = shapes[len(belows) - 1].color
        belows.append(c)
    frees = [None] * (n + 1)
    covered = np.zeros_like(T, dtype=bool)
    frees[n] = ~covered
    for k in range(n - 1, -1, -1):
        x0, y0, m = covs[k]
        if m is not None:
            covered = covered.copy()
            covered[y0:y0 + m.shape[0], x0:x0 + m.shape[1]] |= m
        frees[k] = ~covered
    return belows, frees


def _regions(region, lab, objs):
    """Connected parts of region to propose shapes for: the 8-connected ones,
    plus the 4-connected parts of those that split, since shapes that touch
    only at a corner (a checkerboard, stacked tiles) form one 8-connected
    region whose bounding box fits neither."""
    for idx, sl in objs:
        comp = lab[sl] == idx
        parts = [(comp, sl)]
        lab4, n4 = ndimage.label(comp)
        if n4 > 1:
            for i, sub in enumerate(ndimage.find_objects(lab4), start=1):
                (ys, xs), (oy, ox) = sub, sl
                parts.append((lab4[sub] == i,
                              (slice(oy.start + ys.start, oy.start + ys.stop),
                               slice(ox.start + xs.start, ox.start + xs.stop))))
        for comp, (ys, xs) in parts:
            if (ys.stop - ys.start) * (xs.stop - xs.start) >= 16:
                yield comp, xs, ys


def greedy(T: np.ndarray, bg: int, colors, max_shapes=40, log=None,
           min_gain=MIN_GAIN, per_color=3, bbox_starts=True, outlines=False, also=(),
           start=(), no_polygons=(), pal=None, rho=None, motifs=True):
    """Add shapes one at a time, each at whatever depth in the stack fixes the
    most pixels. Inserting below existing shapes lets the search build rings,
    eyes and other nested figures that no top-only greedy can.

    Returns {min_gain: shapes}. also: higher thresholds to report too; a run
    with a higher threshold would mostly retrace this one and stop where no
    shape fixes that many pixels, so the stack at that point stands in for it.
    start: a stack to add to. no_polygons: colors to draw without polygons.
    pal, rho: when given, each step picks the climbed shape with the best
    pixels fixed / rho minus its estimated characters (see char_cost), so a
    cheap shape beats a costly one that fixes about as many pixels.
    motifs: also propose motifs of the kinds in MOTIFS (see best_motif)."""
    shapes: list[Shape] = list(start)
    out = {}
    for _ in range(max_shapes):
        belows, frees = _layers(T, bg, shapes)
        C = belows[-1]
        wrong = C != T
        pool = {}
        forced = []
        for c in colors:
            region = wrong & (T == c)
            if region.sum() < min_gain:
                continue
            depths = range(len(belows)) if INSERT_ANYWHERE else [len(belows) - 1]
            AB = [(k, *_masks(T, belows[k], c, frees[k])) for k in depths]
            lab, n = ndimage.label(region, structure=np.ones((3, 3)))
            objs = list(enumerate(ndimage.find_objects(lab), start=1))
            # The plain bounding box of the biggest regions, on top of the
            # stack, always gets climbed: from there a climb peels a compound
            # region (a cross, an I-beam) down to its largest bar.
            sizes = ndimage.sum(region, lab, [i for i, _ in objs]) if objs else []
            for (idx, sl), _ in sorted(zip(objs, sizes), key=lambda t: -t[1])[:3 if bbox_starts else 0]:
                ys, xs = sl
                forced.append((len(belows) - 1, Shape(xs.start, ys.start, xs.stop - xs.start,
                                                      ys.stop - ys.start, c)))
            for comp, xs, ys in _regions(region, lab, objs):
                for cand in candidates(c, comp, xs.start, ys.start, outlines):
                    if cand.poly and c in no_polygons:
                        continue
                    x0, y0, m = coverage(cand)
                    if m is None:
                        continue
                    hh, ww = m.shape
                    # each candidate enters at its best depth only, so that a
                    # few shapes at many depths don't fill every start
                    g, k = max(((np.count_nonzero(A[y0:y0 + hh, x0:x0 + ww] & m)
                                 - np.count_nonzero(B[y0:y0 + hh, x0:x0 + ww] & m), -k)
                                for k, A, B in AB))
                    pool.setdefault(repr(cand), (g, -k, cand))
        if not pool and not forced:
            break
        pool = sorted(pool.values(), key=lambda t: -t[0])
        # Climb the best starts overall, plus the best few for every color:
        # a start can score badly (a bounding box over a compound region)
        # and still climb to the right shape.
        starts, counts = [], {}
        for item in pool:
            c = item[2].color
            if len(starts) < TOP_STARTS or counts.get(c, 0) < per_color:
                starts.append(item)
                counts[c] = counts.get(c, 0) + 1
        starts += [(None, k, cand) for k, cand in forced]
        best, best_k, best_g, best_v = None, None, min_gain - 1, -math.inf
        seen, tables, climbed = set(), {}, []
        for g0, k, cand in starts:
            key = (k, repr(cand))
            if key in seen:
                continue
            seen.add(key)
            if (k, cand.color) not in tables:
                A, B = _masks(T, belows[k], cand.color, frees[k])
                tables[k, cand.color] = A, B, area_sums(A, B)
            A, B, sums = tables[k, cand.color]
            s, g = hill_climb(cand, A, B, sums=sums)
            if g < min_gain:
                continue
            v = g if rho is None else g / rho - char_cost(s, shapes, pal)
            climbed.append((v, s, k))
            if v > best_v:
                best, best_k, best_g, best_v = s, k, g, v
        if best is None:
            break
        for g in also:
            if best_g < g and g not in out:
                out[g] = list(shapes)
        added = [best]
        if motifs and MOTIFS and pal is not None and (MOTIF_GATE is None or MOTIF_GATE(shapes)):
            motif = best_motif(T, bg, pal, shapes, best, best_k, climbed, tables, min_gain, belows, frees)
            if motif is not None:
                best_k, added = motif
        shapes[best_k:best_k] = added
        if log:
            log(f"  + at depth {best_k}: {added}  fixes {best_g}px, wrong now {error(T, bg, shapes)}")
    out[min_gain] = shapes
    return {g: out.get(g, shapes) for g in (min_gain, *also)}


SCALE_MOVES = True     # turned shapes also grow with their corners (see _moves)
# Motif kinds to propose (see motifs.py) as well as single shapes: "seeded"
# (mirrors, copies and turns of the best climbed shapes), "symmetric" (a
# symmetric region's piece, climbed, with its images) and "nest" (a ring
# drawn as filled shapes inside each other).
MOTIFS = {"nest"}
MOTIF_SEEDS = 3        # climbed shapes that seed motifs, best first
MOTIF_SCORED = 4       # compositions per step scored by their emitted code
MOTIF_RHO = 0.5        # wrong pixels per character when scoring a step


def structured(T, belows, frees, k, min_gain):
    """Motifs read off the picture, at depth k: for each color region still
    wrong that has a symmetry (motifs.symmetries), candidates fitted to one
    piece of it, climbed on that piece, and composed with their images.
    [(pixels fixed, depth, shapes, kind)]."""
    out = []
    wrong = belows[k] != T
    for c in np.unique(T[wrong]):
        region = wrong & (T == c)
        if region.sum() < 2 * min_gain:
            continue
        A, B = _masks(T, belows[k], c, frees[k])
        sums = area_sums(A, B)
        for kind, params, piece in motifs.symmetries(region) if "symmetric" in MOTIFS else ():
            Ap = A & piece
            sums_p = area_sums(Ap, B)
            ys, xs = np.nonzero(piece)
            comp = piece[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
            best = None
            for cand in candidates(int(c), comp, int(xs.min()), int(ys.min())):
                s, g = hill_climb(cand, Ap, B, sums=sums_p)
                if best is None or g > best[1]:
                    best = (s, g)
            if best is None or best[1] < min_gain:
                continue
            s = best[0]
            copies = motifs.compose(kind, params, s)
            gains = [gain(t, A, B, sums) for t in copies]
            if min(gains) >= min_gain:
                out.append((gain(s, A, B, sums) + sum(gains), k, [s] + copies, "symmetric-" + kind))
        layers = motifs.nest(T, region) if "nest" in MOTIFS else []
        if layers:
            stack = [fit_mask(c2, m) for c2, m in layers]
            if all(stack):
                canvas = belows[k].copy()
                for t in stack:
                    x0, y0, m = coverage(t)
                    if m is not None:
                        canvas[y0:y0 + m.shape[0], x0:x0 + m.shape[1]][m] = t.color
                before = belows[k] == T
                net = int(((canvas == T) & ~before).sum() - ((canvas != T) & before).sum())
                if net >= min_gain:
                    out.append((net, k, stack, "nest"))
    return out


def fit_mask(c, mask):
    """The candidate shape that, climbed, best covers mask and nothing else."""
    ys, xs = np.nonzero(mask)
    if len(xs) < 16:
        return None
    outside = ~mask
    sums = area_sums(mask, outside)
    best = None
    for cand in candidates(c, mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1], int(xs.min()), int(ys.min())):
        s, g = hill_climb(cand, mask, outside, sums=sums)
        if best is None or g > best[1]:
            best = (s, g)
    return best[0]


def best_motif(T, bg, pal, shapes, best, best_k, climbed, tables, min_gain, belows, frees):
    """(depth, shapes to insert) for a motif that beats adding `best` alone,
    or None. Seeds are the best climbed shapes; each composition keeps the
    copies that fix at least min_gain pixels where the seed goes. The most
    promising compositions, by pixels fixed, are scored by what the step
    leaves: emitted characters plus wrong pixels / MOTIF_RHO."""
    proposals = []
    for _, s, k in sorted(climbed, key=lambda t: -t[0])[:MOTIF_SEEDS if "seeded" in MOTIFS else 0]:
        A, B, sums = tables[k, s.color]
        for kind, comp in motifs.compositions(T, s):
            keep = [t for t in comp if gain(t, A, B, sums) >= min_gain]
            if not keep or (kind == "turns" and len(keep) < len(comp)):
                continue
            total = gain(s, A, B, sums) + sum(gain(t, A, B, sums) for t in keep)
            proposals.append((total, k, [s] + keep, "seeded-" + kind))
    proposals += structured(T, belows, frees, len(shapes), min_gain)
    if not proposals:
        return None

    def J(stack):
        return len(codegen.emit(pal, bg, stack, grouping="greedy")[0]) + error(T, bg, stack) / MOTIF_RHO

    base = J(shapes[:best_k] + [best] + shapes[best_k:])
    scored = [(J(shapes[:k] + add + shapes[k:]), k, add, kind, total)
              for total, k, add, kind in sorted(proposals, key=lambda t: -t[0])[:MOTIF_SCORED]]
    if MOTIF_POLICY is not None:
        return MOTIF_POLICY(T, shapes, best, base, scored)
    j, k, add, _, _ = min(scored, key=lambda t: t[0])
    return (k, add) if j < base - 1e-9 else None


# A hook for experiments (bench/proposals.py): called with (T, shapes, best,
# J of adding best, [(J, depth, shapes, kind, pixels fixed)]) instead of the
# rule above, and returns (depth, shapes) or None. MOTIF_GATE(shapes), if
# set, says whether to look for motifs at all at this step.
MOTIF_POLICY = None
MOTIF_GATE = None


def char_cost(s: Shape, shapes, pal) -> int:
    """Characters that adding s would cost, roughly: its own element, or a
    box-shadow entry when it is a shifted copy of a shape already there."""
    cost = codegen.element_cost(s, pal)
    color = codegen.color_css(pal[s.color])
    for a in shapes:
        sh = codegen.shadow_of(a, s)
        if sh is not None:
            cost = min(cost, len(codegen.shadow_entry(*sh, color)) + 1)
    return cost


def _layer_masks(T, bg, shapes, i):
    below = render_labels(bg, shapes[:i])
    above = np.zeros_like(T, dtype=bool)
    for s in shapes[i + 1:]:
        x0, y0, m = coverage(s)
        if m is not None:
            above[y0:y0 + m.shape[0], x0:x0 + m.shape[1]] |= m
    return below, ~above


def error(T, bg, shapes) -> int:
    return int((render_labels(bg, shapes) != T).sum())


def _bbox_union(a: Shape, b: Shape):
    ax0, ay0, ax1, ay1 = a.bbox()
    bx0, by0, bx1, by1 = b.bbox()
    if ax0 > bx1 + 2 or bx0 > ax1 + 2 or ay0 > by1 + 2 or by0 > ay1 + 2:
        return None
    return min(ax0, bx0), min(ay0, by0), max(ax1, bx1), max(ay1, by1)


def merge(T, bg, shapes, min_gain=MIN_GAIN, log=None):
    """Replace two touching same-color shapes by one when the picture barely
    changes. Greedy search often builds a disc from two halves because a half
    fixes more pixels at the moment it is added."""
    shapes = list(shapes)
    changed = True
    while changed:
        changed = False
        base = error(T, bg, shapes)
        for i in range(len(shapes)):
            for j in range(i + 1, len(shapes)):
                a, b = shapes[i], shapes[j]
                if a.color != b.color or a.poly or b.poly:
                    continue
                box = _bbox_union(a, b)
                if box is None:
                    continue
                rest = shapes[:i] + shapes[i + 1:j] + shapes[j + 1:]
                x0, y0, x1, y1 = box
                comp = np.ones((y1 - y0, x1 - x0), dtype=bool)
                e_rest = error(T, bg, rest)
                belows, frees = _layers(T, bg, rest)
                best = None
                for depth in sorted({i, j - 1}):
                    A, B = _masks(T, belows[depth], a.color, frees[depth])
                    sums = area_sums(A, B)
                    for n_c, cand in enumerate(candidates(a.color, comp, x0, y0)):
                        if cand.poly:       # only polygons follow
                            break
                        if cand.rot or 3 <= n_c <= 8:
                            continue
                        c2, g = hill_climb(cand, A, B, sums=sums)
                        if best is None or e_rest - g < best[0]:
                            best = (e_rest - g, rest[:depth] + [c2] + rest[depth:])
                if best and best[0] - base < min_gain:
                    if log:
                        log(f"  merged two shapes, error {base} -> {best[0]}")
                    shapes, changed = best[1], True
                    break
            if changed:
                break
    return shapes


def refine(T, bg, shapes, rounds=2, log=None, min_gain=MIN_GAIN):
    shapes = merge(T, bg, list(shapes), min_gain, log)
    for _ in range(rounds):
        # re-fit each shape against its final surroundings
        for i in range(len(shapes)):
            below, free = _layer_masks(T, bg, shapes, i)
            A, B = _masks(T, below, shapes[i].color, free)
            shapes[i], _ = hill_climb(shapes[i], A, B, steps=(4, 2, 1))
        # drop shapes that don't pay for themselves
        base = error(T, bg, shapes)
        i = len(shapes) - 1
        while i >= 0:
            trial = shapes[:i] + shapes[i + 1:]
            e = error(T, bg, trial)
            if e - base < min_gain:
                shapes, base = trial, e
            i -= 1
    shapes = snap(T, bg, shapes)
    return shapes


def snap(T, bg, shapes, tol=0):
    """Round coordinates to multiples of 5 or 10 when it costs no pixels.
    Round numbers are no shorter, but equal sizes let shapes share CSS."""
    shapes = list(shapes)
    for i, s in enumerate(shapes):
        below, free = _layer_masks(T, bg, shapes, i)
        A, B = _masks(T, below, s.color, free)
        g0 = gain(s, A, B)
        for attr in ("x", "y", "w", "h"):
            v = getattr(s, attr)
            for q in (10, 5, 1):
                nv = round(v / q) * q
                if nv == v or (attr in "wh" and nv <= 0):
                    continue
                cand = s.copy(**{attr: nv})
                if gain(cand, A, B) >= g0 - tol:
                    s = cand
                    break
        shapes[i] = s
    return shapes


def decompose(img: np.ndarray, log=None, min_gains=(MIN_GAIN,), per_color=3, bbox_starts=True,
              base="flat", outlines=False, rho=None, motifs=True):
    """Returns (palette, base layer, labels, {min_gain: shapes}), one stack per
    threshold in min_gains (see greedy), or None.

    base: "flat" (a background color) or "gradient" (a fitted linear-gradient;
    returns None when no gradient fits). outlines: propose polygons fitted to
    region outlines (see candidates). rho: weigh characters while searching
    (see greedy)."""
    pal, T = extract_palette(img)
    if base == "gradient":
        bg = fit_gradient(T, len(pal))
        if bg is None:
            return None
        bg = soften(bg, img, pal)
        colors = list(range(len(pal)))
        if log:
            log(f"  gradient base: {bg}")
    else:
        bg = background(T)
        colors = [c for c in range(len(pal)) if c != bg] + [bg]
    lo, *also = sorted(min_gains)
    stacks = greedy(T, bg, colors, log=log, min_gain=lo, per_color=per_color,
                    bbox_starts=bbox_starts, outlines=outlines, also=also, pal=pal, rho=rho, motifs=motifs)
    return pal, bg, T, {g: refine(T, bg, s, log=log, min_gain=g) for g, s in stacks.items()}

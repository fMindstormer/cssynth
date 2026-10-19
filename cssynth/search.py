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

import math

import numpy as np
from scipy import ndimage

from .shapes import Gradient, H, Shape, W, _in_polygon, base_labels, coverage, gradient_rgb, render_labels

MIN_COLOR_PX = 40
MIN_GAIN = 25          # pixels a shape must fix to be worth its characters


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
    sums: summed-area table of A - B (see area_sums), which makes boxes cheap."""
    if sums is not None and not s.rot % 360 and not s.ell and not s.poly:
        return _box_gain(s, A, B, sums)
    x0, y0, m = coverage(s)
    if m is None:
        return -10**9
    h, w = m.shape
    return (np.count_nonzero(A[y0:y0 + h, x0:x0 + w] & m)
            - np.count_nonzero(B[y0:y0 + h, x0:x0 + w] & m))


def area_sums(A, B) -> np.ndarray:
    S = np.zeros((A.shape[0] + 1, A.shape[1] + 1), dtype=np.int32)
    S[1:, 1:] = (A.astype(np.int32) - B).cumsum(0).cumsum(1)
    return S


def _box_gain(s: Shape, A, B, S) -> int:
    """gain() for an unrotated box: the sum over its rectangle from the table,
    minus what its rounded corners cut away. Cuts lie in disjoint corner
    blocks (CSS scales radii so adjacent ones never overlap), and each is
    computed exactly as coverage() does, so the result is identical."""
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
    g = int(S[j1, i1] - S[j0, i1] - S[j1, i0] + S[j0, i0])
    if not any(s.radii):
        return g
    hw, hh = s.w / 2, s.h / 2
    cx, cy = s.x + hw, s.y + hh
    for (rx, ry), (sx, sy) in zip(s.corner_radii(), ((-1, -1), (1, -1), (1, 1), (-1, 1))):
        if rx <= 0 or ry <= 0:
            continue
        # the corner block: pixels whose centers lie beyond the arc's center
        ccx, ccy = cx + sx * (hw - rx), cy + sy * (hh - ry)
        if sx < 0:
            a0, a1 = i0, min(i1, max(i0, math.ceil(ccx - 0.5)))
        else:
            a0, a1 = max(i0, min(i1, math.floor(ccx - 0.5) + 1)), i1
        if sy < 0:
            b0, b1 = j0, min(j1, max(j0, math.ceil(ccy - 0.5)))
        else:
            b0, b1 = max(j0, min(j1, math.floor(ccy - 0.5) + 1)), j1
        if a1 <= a0 or b1 <= b0:
            continue
        u = (np.arange(a0, a1) + 0.5 - cx)[None, :]
        v = (np.arange(b0, b1) + 0.5 - cy)[:, None]
        cu, cv = sx * (hw - rx), sy * (hh - ry)
        du, dv = (u - cu) / rx, (v - cv) / ry
        cut = ((u - cu) * sx > 0) & ((v - cv) * sy > 0) & (du * du + dv * dv > 1)
        g -= (np.count_nonzero(A[b0:b1, a0:a1] & cut) - np.count_nonzero(B[b0:b1, a0:a1] & cut))
    return g


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


def _vertex_delta(old: Shape, new: Shape, A, B):
    """gain(new) - gain(old) when the polygons differ in one vertex, or None.
    Only pixels near the vertex's two edges can change, so both polygons are
    tested on that window alone (the even-odd test of a pixel does not depend
    on which other pixels are sampled, so this is exact)."""
    if not (old.poly and new.poly) or len(old.poly) != len(new.poly) or new.w <= 0 or new.h <= 0:
        return None
    diff = [i for i, (p, q) in enumerate(zip(old.poly, new.poly)) if p != q]
    if len(diff) != 1:
        return None
    i, n = diff[0], len(old.poly)
    pts = [old.poly[i - 1], old.poly[i], new.poly[i], old.poly[(i + 1) % n]]
    x0 = max(0, min(p[0] for p in pts))
    x1 = min(W, max(p[0] for p in pts) + 1)
    y0 = max(0, min(p[1] for p in pts))
    y1 = min(H, max(p[1] for p in pts) + 1)
    if x1 <= x0 or y1 <= y0:
        return 0
    xs, ys = np.arange(x0, x1) + 0.5, np.arange(y0, y1) + 0.5
    change = _in_polygon(xs, ys, new.poly).astype(np.int8) - _in_polygon(xs, ys, old.poly)
    a, b = A[y0:y1, x0:x1], B[y0:y1, x0:x1]
    return int((change * a).sum() - (change * b).sum())


def hill_climb(s: Shape, A, B, steps=(16, 8, 4, 2, 1)) -> tuple[Shape, int]:
    sums = area_sums(A, B)
    seen = {}

    def score(c, parent=None, parent_gain=None):
        k = repr(c)
        if k not in seen:
            d = _vertex_delta(parent, c, A, B) if parent is not None and parent_gain > -10**9 else None
            seen[k] = parent_gain + d if d is not None else gain(c, A, B, sums)
        return seen[k]

    best, bg = s, score(s)
    for step in steps:
        improved = True
        while improved:
            improved = False
            for cand in _moves(best, step):
                g = score(cand, best, bg)
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
           start=(), no_polygons=()):
    """Add shapes one at a time, each at whatever depth in the stack fixes the
    most pixels. Inserting below existing shapes lets the search build rings,
    eyes and other nested figures that no top-only greedy can.

    Returns {min_gain: shapes}. also: higher thresholds to report too; a run
    with a higher threshold would mostly retrace this one and stop where no
    shape fixes that many pixels, so the stack at that point stands in for it.
    start: a stack to add to. no_polygons: colors to draw without polygons."""
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
            AB = [_masks(T, belows[k], c, frees[k]) for k in range(len(belows))]
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
                                for k, (A, B) in enumerate(AB)))
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
            if len(starts) < 10 or counts.get(c, 0) < per_color:
                starts.append(item)
                counts[c] = counts.get(c, 0) + 1
        starts += [(None, k, cand) for k, cand in forced]
        best, best_k, best_g = None, None, min_gain - 1
        seen = set()
        for g0, k, cand in starts:
            key = (k, repr(cand))
            if key in seen:
                continue
            seen.add(key)
            A, B = _masks(T, belows[k], cand.color, frees[k])
            s, g = hill_climb(cand, A, B)
            if g > best_g:
                best, best_k, best_g = s, k, g
        if best is None:
            break
        for g in also:
            if best_g < g and g not in out:
                out[g] = list(shapes)
        shapes.insert(best_k, best)
        if log:
            log(f"  + at depth {best_k}: {best}  fixes {best_g}px, wrong now {error(T, bg, shapes)}")
    out[min_gain] = shapes
    return {g: out.get(g, shapes) for g in (min_gain, *also)}


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
                    for n_c, cand in enumerate(candidates(a.color, comp, x0, y0)):
                        if cand.poly or cand.rot or 3 <= n_c <= 8:
                            continue
                        c2, g = hill_climb(cand, A, B)
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
              base="flat", outlines=False):
    """Returns (palette, base layer, labels, {min_gain: shapes}), one stack per
    threshold in min_gains (see greedy), or None.

    base: "flat" (a background color) or "gradient" (a fitted linear-gradient;
    returns None when no gradient fits). outlines: propose polygons fitted to
    region outlines (see candidates)."""
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
                    bbox_starts=bbox_starts, outlines=outlines, also=also)
    return pal, bg, T, {g: refine(T, bg, s, log=log, min_gain=g) for g, s in stacks.items()}

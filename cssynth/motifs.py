"""Motifs: several shapes proposed together as one step of the search.

Pictures are full of structure that the code can share: a shape and its
mirror image, copies at a constant offset (box-shadows), leaves turned about
a common center. The greedy search adds one shape at a time, scored by
pixels, so it can take a large shape that covers a whole symmetric group
instead of its parts, and never sees that the parts would share CSS.

Here a climbed shape seeds compositions: its mirror images across the
canvas's and its color region's center lines, its copies on the other
regions of its color that have its size, and its turns about the region's
or the canvas's center. Each composition keeps the copies that fix more
pixels than they break, and the search scores it, like a single shape, by
the code it would actually emit (see search.greedy).
"""

from __future__ import annotations

import math

import numpy as np
from scipy import ndimage

from .shapes import H, Shape, W

TURNS = (2, 3, 4, 5, 6, 8)


def mirrored(s: Shape, axis: str, at: float) -> Shape:
    """s reflected across the vertical (axis "x") or horizontal ("y") line
    through `at`."""
    if s.poly:
        if axis == "x":
            return Shape.polygon([(2 * at - a, b) for a, b in s.poly], s.color)
        return Shape.polygon([(a, 2 * at - b) for a, b in s.poly], s.color)
    tl, tr, br, bl = s.radii
    if axis == "x":
        return s.copy(x=2 * at - s.x - s.w, radii=(tr, tl, bl, br), rot=-s.rot % 360)
    return s.copy(y=2 * at - s.y - s.h, radii=(bl, br, tr, tl), rot=-s.rot % 360)


def turned(s: Shape, cx: float, cy: float, deg: float) -> Shape:
    """s turned by deg (clockwise on screen) about (cx, cy). Quarter turns of
    an unturned box stay unturned: its size swaps and its corners shift."""
    t = math.radians(deg)
    if s.poly:
        return Shape.polygon([(cx + (a - cx) * math.cos(t) - (b - cy) * math.sin(t),
                               cy + (a - cx) * math.sin(t) + (b - cy) * math.cos(t)) for a, b in s.poly], s.color)
    mx, my = s.x + s.w / 2, s.y + s.h / 2
    nx = cx + (mx - cx) * math.cos(t) - (my - cy) * math.sin(t)
    ny = cy + (mx - cx) * math.sin(t) + (my - cy) * math.cos(t)
    q = round(deg / 90)
    if not s.rot % 360 and abs(deg - 90 * q) < 1e-9:
        w, h = (s.h, s.w) if q % 2 else (s.w, s.h)
        r = s.radii[-q % 4:] + s.radii[:-q % 4]
        return s.copy(x=round(nx - w / 2), y=round(ny - h / 2), w=w, h=h, radii=r)
    return s.copy(x=round(nx - s.w / 2), y=round(ny - s.h / 2), rot=round((s.rot + deg) % 360))


def _regions(T, c):
    lab, n = ndimage.label(T == c, structure=np.ones((3, 3)))
    return [(sl, int((lab[sl] == i + 1).sum())) for i, sl in enumerate(ndimage.find_objects(lab))]


def compositions(T: np.ndarray, s: Shape):
    """(kind, shapes) that, with s, may form a motif: "mirror", "copies" or
    "turns". Candidates only: the caller keeps the copies that help (all of
    them, for turns) and scores the result."""
    c = s.color
    region = T == c
    if not region.any():
        return
    ys, xs = np.nonzero(region)
    rx, ry = (xs.min() + xs.max() + 1) / 2, (ys.min() + ys.max() + 1) / 2
    # mirror images across the canvas's and the region's center lines
    for axis, centers in (("x", (W / 2, rx)), ("y", (H / 2, ry))):
        for at in dict.fromkeys(centers):
            yield "mirror", [mirrored(s, axis, at)]
    # copies on the other regions of this color that have s's size
    regs = _regions(T, c)
    x0, y0, x1, y1 = s.bbox()
    home = max(regs, key=lambda r: _overlap(r[0], (x0, y0, x1, y1)), default=None)
    if home is not None:
        (hy, hx), _ = home
        copies = []
        for (sy, sx), _ in regs:
            if (sy, sx) == (hy, hx):
                continue
            if abs((sx.stop - sx.start) - (hx.stop - hx.start)) <= 2 and abs(
                    (sy.stop - sy.start) - (hy.stop - hy.start)) <= 2:
                copies.append(s.moved(sx.start - hx.start, sy.start - hy.start))
        if copies:
            yield "copies", copies
    # turns about the region's and the canvas's center
    for cx, cy in dict.fromkeys(((rx, ry), (W / 2, H / 2))):
        for n in TURNS:
            yield "turns", [turned(s, cx, cy, 360 * k / n) for k in range(1, n)]


def _overlap(sl, box):
    (sy, sx) = sl
    x0, y0, x1, y1 = box
    return max(0, min(sx.stop, x1) - max(sx.start, x0)) * max(0, min(sy.stop, y1) - max(sy.start, y0))


SYMMETRY = 0.9          # share of a region's pixels whose image must also be in it


def symmetries(region: np.ndarray):
    """(kind, parameters, piece) for each symmetry of a region (a bool mask):
    ("mirror", (axis, at), the half before the axis) across its bounding
    box's center lines, and ("turns", (cx, cy, n), one sector of the turn)
    about its centroid. Many regions are symmetric only because they are one
    plain shape; the search finds out which compositions pay."""
    ys, xs = np.nonzero(region)
    if len(xs) < 50:
        return
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    if (region[ys, x0 + x1 - 1 - xs]).mean() >= SYMMETRY:
        half = region.copy()
        half[:, (x0 + x1) // 2:] = False
        yield "mirror", ("x", (x0 + x1) / 2), half
    if (region[y0 + y1 - 1 - ys, xs]).mean() >= SYMMETRY:
        half = region.copy()
        half[(y0 + y1) // 2:, :] = False
        yield "mirror", ("y", (y0 + y1) / 2), half
    cx, cy = xs.mean() + 0.5, ys.mean() + 0.5
    px, py = xs + 0.5 - cx, ys + 0.5 - cy
    ang = np.arctan2(py, px) % (2 * math.pi)
    for n in TURNS:
        t = 2 * math.pi / n
        qx = np.floor(cx + px * math.cos(t) - py * math.sin(t)).astype(int)
        qy = np.floor(cy + px * math.sin(t) + py * math.cos(t)).astype(int)
        ok = (qx >= 0) & (qx < W) & (qy >= 0) & (qy < H)
        if ok.mean() < SYMMETRY or region[qy[ok], qx[ok]].sum() < SYMMETRY * len(xs):
            continue
        # a sector that starts where the region is thinnest, between two copies
        hist = np.bincount((ang / (2 * math.pi) * 72).astype(int) % 72, minlength=72)
        a0 = (hist.argmin() + 0.5) * 2 * math.pi / 72
        piece = np.zeros_like(region)
        piece[ys, xs] = (ang - a0) % (2 * math.pi) < t
        yield "turns", (cx, cy, n), piece


def compose(kind, params, s: Shape) -> list[Shape]:
    """The copies of s that a symmetry from symmetries() calls for."""
    if kind == "mirror":
        return [mirrored(s, *params)]
    cx, cy, n = params
    return [turned(s, cx, cy, 360 * k / n) for k in range(1, n)]


NEST_HOLE = 0.1         # a region is a ring when its holes are at least this share of it filled


def nest(T: np.ndarray, region: np.ndarray, depth: int = 4):
    """For a ring-like region (one with holes), the layers that draw it as
    filled shapes stacked inside each other, outermost first: [(color,
    mask)]. A filled disc of the ring's color, then the hole drawn the same
    way in the color that lines it, and so on inward. Each layer on its own
    breaks the pixels inside it, so a search adding one shape at a time
    never starts it; as one motif it can pay. [] unless the region has
    exactly one hole."""
    layers = []
    c = int(np.bincount(T[region]).argmax())
    filled = ndimage.binary_fill_holes(region)
    # one hole, as in a ring; a frame with several windows is drawn fine one
    # shape at a time, and one shape fitted over all its windows is not
    while (depth and filled.sum() and (filled & ~region).sum() >= NEST_HOLE * filled.sum()
           and ndimage.label(filled & ~region)[1] == 1):
        layers.append((c, filled))
        hole = filled & ~region
        # the color lining the hole: what its outermost pixels show
        rim = hole & ~ndimage.binary_erosion(hole)
        c = int(np.bincount(T[rim]).argmax())
        region = hole & (T == c)
        filled = ndimage.binary_fill_holes(region) & hole
        depth -= 1
    if layers:
        layers.append((c, filled))
    return layers

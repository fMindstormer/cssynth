"""Shapes the compiler can emit, and a rasterizer that matches how Chromium
draws them (closely enough to drive the search).

A shape is one CSS box: position, size, a color, corner radii and a rotation.
Corner radii are either `ell` (border-radius:50%, an ellipse) or four circular
radii in px (top-left, top-right, bottom-right, bottom-left).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

import numpy as np

W, H = 400, 300


@dataclass
class Shape:
    x: float
    y: float
    w: float
    h: float
    color: int                       # palette index
    radii: tuple = (0, 0, 0, 0)      # tl, tr, br, bl (circular, px)
    ell: bool = False                # border-radius:50%
    rot: float = 0.0                 # degrees, about the center
    poly: tuple | None = None        # clip-path polygon, absolute (x, y) vertices

    @staticmethod
    def polygon(pts, color) -> "Shape":
        pts = tuple((int(round(px)), int(round(py))) for px, py in pts)
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return Shape(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys), color, poly=pts)

    def copy(self, **kw) -> "Shape":
        return replace(self, **kw)

    def pos(self) -> tuple[float, float]:
        """Where Chromium actually puts the box. A rotated (transformed) box's
        fractional position is rounded to whole pixels, half up, before the
        rotation is applied; other boxes are used as given."""
        if self.rot % 360:
            return math.floor(self.x + 0.5), math.floor(self.y + 0.5)
        return self.x, self.y

    def corner_radii(self) -> list[tuple[float, float]]:
        """(rx, ry) per corner after CSS's proportional scale-down."""
        if self.ell:
            r = [(self.w / 2, self.h / 2)] * 4
        else:
            r = [(float(v), float(v)) for v in self.radii]
        # CSS: if adjacent radii overflow a side, scale all radii by the same f.
        f = 1.0
        sides = [
            (r[0][0] + r[1][0], self.w),   # top
            (r[3][0] + r[2][0], self.w),   # bottom
            (r[0][1] + r[3][1], self.h),   # left
            (r[1][1] + r[2][1], self.h),   # right
        ]
        for s, length in sides:
            if s > 0 and length / s < f:
                f = length / s
        return [(a * f, b * f) for a, b in r]

    def bbox(self) -> tuple[int, int, int, int]:
        """Integer pixel bounds (x0, y0, x1, y1), clipped to the canvas."""
        if self.rot % 180 == 0:
            x0, y0, x1, y1 = self.x, self.y, self.x + self.w, self.y + self.h
        else:
            px_, py_ = self.pos()
            cx, cy = px_ + self.w / 2, py_ + self.h / 2
            t = math.radians(self.rot)
            ex = abs(self.w / 2 * math.cos(t)) + abs(self.h / 2 * math.sin(t))
            ey = abs(self.w / 2 * math.sin(t)) + abs(self.h / 2 * math.cos(t))
            x0, y0, x1, y1 = cx - ex, cy - ey, cx + ex, cy + ey
        return (max(0, int(math.floor(x0))), max(0, int(math.floor(y0))),
                min(W, int(math.ceil(x1))), min(H, int(math.ceil(y1))))


def coverage(s: Shape, ss: int = 1):
    """Coverage of the shape over its bbox.

    Returns (x0, y0, mask) where mask is bool (ss=1, pixel-center sampling) or
    float in [0, 1] (ss>1, ss*ss supersampling)."""
    x0, y0, x1, y1 = s.bbox()
    if x1 <= x0 or y1 <= y0 or s.w <= 0 or s.h <= 0:
        return x0, y0, None
    offs = (np.arange(ss) + 0.5) / ss
    xs = (np.arange(x0, x1)[:, None] + offs[None, :]).ravel()
    ys = (np.arange(y0, y1)[:, None] + offs[None, :]).ravel()
    px_, py_ = s.pos()
    cx, cy = px_ + s.w / 2, py_ + s.h / 2
    if s.poly:
        inside = _in_polygon(xs, ys, s.poly)
    elif s.rot % 360:
        X, Y = np.meshgrid(xs, ys)
        t = math.radians(-s.rot)
        c, n = math.cos(t), math.sin(t)
        u, v = (X - cx) * c - (Y - cy) * n, (X - cx) * n + (Y - cy) * c
        inside = _in_box(u, v, s)
    else:
        # axis-aligned: a row of u and a column of v, broadcast together
        inside = _in_box((xs - cx)[None, :], (ys - cy)[:, None], s)
    if ss == 1:
        return x0, y0, inside
    m = inside.reshape(y1 - y0, ss, x1 - x0, ss).mean(axis=(1, 3))
    return x0, y0, m


def _in_box(u, v, s: Shape) -> np.ndarray:
    hw, hh = s.w / 2, s.h / 2
    inside = (np.abs(u) <= hw) & (np.abs(v) <= hh)
    signs = [(-1, -1), (1, -1), (1, 1), (-1, 1)]       # tl, tr, br, bl
    for (rx, ry), (sx, sy) in zip(s.corner_radii(), signs):
        if rx <= 0 or ry <= 0:
            continue
        ccx, ccy = sx * (hw - rx), sy * (hh - ry)
        du, dv = (u - ccx) / rx, (v - ccy) / ry
        cut = ((u - ccx) * sx > 0) & ((v - ccy) * sy > 0) & (du * du + dv * dv > 1)
        inside = inside & ~cut
    return inside


@dataclass(frozen=True)
class Gradient:
    """A full-frame linear-gradient with hard stops, used as the base layer
    instead of a flat background color.

    angle: CSS degrees (180 = top to bottom, the default; 90 = left to right).
    stops: ((color, end), ...), ends in px along the gradient line, which runs
           through the center and is |W sin a| + |H cos a| long (as in CSS).
           Color i fills [end[i-1], end[i]); the last end is ignored."""
    angle: float
    stops: tuple

    def length(self) -> float:
        t = math.radians(self.angle)
        return abs(W * math.sin(t)) + abs(H * math.cos(t))

    def positions(self, ss: int = 1) -> np.ndarray:
        """Position along the gradient line of every (sub)pixel center."""
        offs = (np.arange(ss) + 0.5) / ss
        xs = (np.arange(W)[:, None] + offs[None, :]).ravel()
        ys = (np.arange(H)[:, None] + offs[None, :]).ravel()
        t = math.radians(self.angle)
        return ((xs[None, :] - W / 2) * math.sin(t) - (ys[:, None] - H / 2) * math.cos(t)
                + self.length() / 2)

    def labels(self, ss: int = 1) -> np.ndarray:
        ends = np.array([e for _, e in self.stops[:-1]], dtype=float)
        cols = np.array([c for c, _ in self.stops], dtype=np.int16)
        return cols[np.searchsorted(ends, self.positions(ss), side="right")]


def base_labels(bg) -> np.ndarray:
    if isinstance(bg, Gradient):
        return bg.labels()
    return np.full((H, W), bg, dtype=np.int16)


def base_rgb(bg, palette, ss: int = 4) -> np.ndarray:
    pal = np.asarray(palette, dtype=np.float64)
    if isinstance(bg, Gradient):
        # Chromium does not antialias hard gradient stops: sample centers only.
        return pal[bg.labels()]
    img = np.empty((H, W, 3), dtype=np.float64)
    img[:] = pal[bg]
    return img


def render_labels(bg, shapes: list[Shape]) -> np.ndarray:
    """bg is a palette index (flat background) or a Gradient."""
    canvas = base_labels(bg).copy()
    for s in shapes:
        x0, y0, m = coverage(s)
        if m is None:
            continue
        sub = canvas[y0:y0 + m.shape[0], x0:x0 + m.shape[1]]
        sub[m] = s.color
    return canvas


def render_rgb(bg, palette, shapes: list[Shape], ss: int = 4) -> np.ndarray:
    """Antialiased render (sRGB-space blending, as browsers do)."""
    img = base_rgb(bg, palette, ss)
    for s in shapes:
        x0, y0, m = coverage(s, ss)
        if m is None:
            continue
        sub = img[y0:y0 + m.shape[0], x0:x0 + m.shape[1]]
        a = m[..., None]
        sub[:] = sub * (1 - a) + np.asarray(palette[s.color], dtype=np.float64) * a
    return np.clip(np.rint(img), 0, 255).astype(np.uint8)


def _in_polygon(xs, ys, pts) -> np.ndarray:
    """Even-odd point-in-polygon test on the grid of sorted sample columns xs
    and rows ys. Each edge crossing a row toggles the samples left of the
    crossing; counting crossings per row and column is a suffix sum."""
    P = np.asarray(pts, dtype=float)
    (xa, ya), (xb, yb) = P.T, np.roll(P, -1, 0).T
    keep = ya != yb
    xa, ya, xb, yb = xa[keep], ya[keep], xb[keep], yb[keep]
    Y = ys[:, None]
    crosses = (Y >= np.minimum(ya, yb)) & (Y < np.maximum(ya, yb))
    xint = xa + (Y - ya) * (xb - xa) / (yb - ya)
    r, e = np.nonzero(crosses)
    idx = np.searchsorted(xs, xint[r, e], side="left")     # samples with X < xint
    # sample c is toggled by crossings with idx > c: the row's total minus a
    # forward running count (uint8 wraps, which keeps the parity)
    counts = np.zeros((len(ys), len(xs) + 1), dtype=np.uint8)
    np.add.at(counts, (r, idx), 1)
    left = np.cumsum(counts[:, :-1], axis=1, dtype=np.uint8)
    total = np.bincount(r, minlength=len(ys)).astype(np.uint8)[:, None]
    return ((total - left) & 1).astype(bool)


def bg_to_json(bg):
    if isinstance(bg, Gradient):
        return {"angle": bg.angle, "stops": [[int(c), float(e)] for c, e in bg.stops]}
    return int(bg)


def bg_from_json(obj):
    if isinstance(obj, dict):
        return Gradient(obj["angle"], tuple((c, e) for c, e in obj["stops"]))
    return int(obj)

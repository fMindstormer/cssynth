import numpy as np

from cssc.search import extract_palette, reduce_polygon, trace_outline
from cssc.shapes import Shape, coverage


def test_trace_outline_of_concave_region_is_exact():
    region = np.zeros((30, 40), dtype=bool)
    region[5:25, 5:15] = True
    region[15:25, 5:35] = True                      # an L
    pts = trace_outline(region)
    assert len(pts) == 6
    x0, y0, m = coverage(Shape.polygon(pts, 1))
    drawn = np.zeros_like(region)
    drawn[y0:y0 + m.shape[0], x0:x0 + m.shape[1]] = m
    assert np.array_equal(drawn, region)


def test_trace_outline_fills_holes():
    ring = np.zeros((20, 20), dtype=bool)
    ring[2:18, 2:18] = True
    ring[6:14, 6:14] = False
    assert sorted(trace_outline(ring)) == [(2, 2), (2, 18), (18, 2), (18, 18)]


def test_reduce_polygon_finds_diamond_corners():
    yy, xx = np.mgrid[:60, :60]
    pts = reduce_polygon(trace_outline(abs(xx - 30) + abs(yy - 30) < 20), 4)
    for want in [(30, 11), (49, 30), (30, 49), (11, 30)]:
        assert min(abs(a - want[0]) + abs(b - want[1]) for a, b in pts) <= 3


def test_extract_palette_ignores_antialiasing():
    img = np.zeros((300, 400, 3), dtype=np.uint8)
    img[:] = (20, 40, 60)
    img[100:200, 100:200] = (220, 200, 180)
    img[100:200, 200] = (120, 120, 120)            # a one-pixel blended edge
    pal, labels = extract_palette(img)
    assert len(pal) == 2
    assert labels.shape == (300, 400)

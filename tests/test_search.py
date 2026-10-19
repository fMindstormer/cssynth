import numpy as np
from scipy import ndimage

from cssynth.search import _regions, _vertex_delta, area_sums, extract_palette, gain, reduce_polygon, trace_outline
from cssynth.shapes import Shape, coverage


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


def test_box_gain_matches_coverage():
    rng = np.random.default_rng(1)
    A = rng.random((300, 400)) < 0.3
    B = (rng.random((300, 400)) < 0.3) & ~A
    sums = area_sums(A, B)
    for _ in range(2000):
        s = Shape(float(rng.integers(-40, 420)) + rng.choice([0, 0.5]), float(rng.integers(-40, 320)),
                  float(rng.integers(1, 250)) + rng.choice([0, 0.5]), float(rng.integers(1, 200)), 1,
                  radii=tuple(int(v) * (rng.random() < 0.6) for v in rng.integers(0, 150, 4)))
        assert gain(s, A, B, sums) == gain(s, A, B)


def test_regions_split_shapes_touching_at_a_corner():
    region = np.zeros((300, 400), dtype=bool)
    region[50:150, 50:150] = True
    region[150:250, 150:250] = True                 # meets the first only at a corner
    lab, _ = ndimage.label(region, structure=np.ones((3, 3)))
    boxes = {(xs.start, ys.start, xs.stop, ys.stop)
             for _, xs, ys in _regions(region, lab, list(enumerate(ndimage.find_objects(lab), 1)))}
    assert {(50, 50, 150, 150), (150, 150, 250, 250)} <= boxes


def test_vertex_delta_matches_full_gain():
    rng = np.random.default_rng(2)
    A = rng.random((300, 400)) < 0.3
    B = (rng.random((300, 400)) < 0.3) & ~A
    for _ in range(300):
        pts = [tuple(int(v) for v in p) for p in rng.integers(-20, 420, (rng.integers(3, 10), 2))]
        old = Shape.polygon(pts, 1)
        i = int(rng.integers(len(pts)))
        moved = pts.copy()
        moved[i] = (pts[i][0] + int(rng.integers(-16, 17)), pts[i][1] + int(rng.integers(-16, 17)))
        new = Shape.polygon(moved, 1)
        d = _vertex_delta(old, new, A, B)
        if d is not None:
            assert gain(old, A, B) + d == gain(new, A, B)

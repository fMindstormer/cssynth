import numpy as np

from cssynth.shapes import Shape, _in_polygon, coverage, render_labels


def naive_in_polygon(xs, ys, pts):
    """Reference even-odd test, one edge at a time over the full grid."""
    X, Y = np.meshgrid(xs, ys)
    inside = np.zeros(X.shape, dtype=bool)
    for (xa, ya), (xb, yb) in zip(pts, pts[1:] + pts[:1]):
        if ya == yb:
            continue
        crosses = (Y >= min(ya, yb)) & (Y < max(ya, yb))
        inside ^= crosses & (X < xa + (Y - ya) * (xb - xa) / (yb - ya))
    return inside


def test_in_polygon_matches_reference():
    rng = np.random.default_rng(0)
    for t in range(200):
        pts = [tuple(int(v) for v in p) for p in rng.integers(0, 60, (rng.integers(3, 14), 2))]
        ss = 4 if t % 2 else 1
        offs = (np.arange(ss) + 0.5) / ss
        xs = (np.arange(60)[:, None] + offs).ravel()
        ys = (np.arange(60)[:, None] + offs).ravel()
        assert np.array_equal(_in_polygon(xs, ys, pts), naive_in_polygon(xs, ys, pts))


def test_box_coverage_is_exact():
    _, _, m = coverage(Shape(10, 20, 30, 40, 1))
    assert m.shape == (40, 30) and m.all()


def test_later_shapes_paint_on_top():
    canvas = render_labels(0, [Shape(0, 0, 100, 100, 1), Shape(25, 25, 50, 50, 2)])
    assert canvas[50, 50] == 2 and canvas[10, 10] == 1 and canvas[200, 200] == 0

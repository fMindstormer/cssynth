import numpy as np
from scipy import ndimage

from cssynth.search import (
    _regions,
    add_parts,
    area_sums,
    char_cost,
    error,
    extract_palette,
    gain,
    parts,
    reduce_polygon,
    soften,
    trace_outline,
)
from cssynth.shapes import Gradient, Shape, base_rgb, coverage, render_labels


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


def test_polygon_gain_matches_coverage():
    rng = np.random.default_rng(2)
    A = rng.random((300, 400)) < 0.3
    B = (rng.random((300, 400)) < 0.3) & ~A
    sums = area_sums(A, B)
    for _ in range(1000):          # includes self-crossing and off-canvas polygons
        pts = [tuple(int(v) for v in p) for p in rng.integers(-40, 440, (rng.integers(3, 12), 2))]
        s = Shape.polygon(pts, 1)
        assert gain(s, A, B, sums) == gain(s, A, B)


def test_turned_and_elliptic_gain_matches_coverage():
    rng = np.random.default_rng(3)
    A = rng.random((300, 400)) < 0.3
    B = (rng.random((300, 400)) < 0.3) & ~A
    sums = area_sums(A, B)
    for _ in range(1000):
        s = Shape(float(rng.integers(-40, 420)) + rng.choice([0, 0.5]), float(rng.integers(-40, 320)),
                  float(rng.integers(1, 250)), float(rng.integers(1, 200)), 1,
                  radii=tuple(int(v) * (rng.random() < 0.5) for v in rng.integers(0, 150, 4)),
                  ell=rng.random() < 0.4, rot=float(rng.integers(-90, 90)) * (rng.random() < 0.6))
        assert gain(s, A, B, sums) == gain(s, A, B)


def test_soften_recovers_a_subpixel_ramp():
    # a target whose edge lies between pixels and is blended over 1.2px, as an
    # antialiased turned edge is; a hard stop at the nearest pixel can't match
    pal = np.array([(20, 160, 70), (250, 200, 30)])
    img = np.rint(base_rgb(Gradient(150.0, ((0, 230.4), (1, 500.0)), (1.2,)), pal)).astype(np.uint8)
    hard = Gradient(150.0, ((0, 230.0), (1, 500.0)))
    soft = soften(hard, img, pal)

    def wrong(g):
        return int((np.abs(base_rgb(g, pal) - img).max(-1) > 8).sum())

    assert wrong(hard) > 100 and wrong(soft) == 0


def test_char_cost_of_a_shifted_copy_is_a_shadow_entry():
    pal = np.array([[255, 255, 255], [200, 30, 30]])
    a = Shape(40, 40, 60, 60, 1)
    full = char_cost(a, [], pal)
    copy = char_cost(Shape(200, 40, 60, 60, 1), [a], pal)
    assert copy < full // 2


def _disc(cx, cy, r):
    yy, xx = np.mgrid[:300, :400] + 0.5
    return (xx - cx) ** 2 + (yy - cy) ** 2 <= r * r


def test_parts_split_touching_discs():
    region = _disc(200, 100, 50) | _disc(200, 200, 50)
    ps = parts(region)
    assert len(ps) == 2
    for p, disc in zip(sorted(ps, key=lambda m: np.nonzero(m)[0].mean()), (_disc(200, 100, 50), _disc(200, 200, 50))):
        assert (p & ~disc).sum() == 0 and (disc & ~p).sum() < 0.03 * disc.sum()


def test_parts_leave_a_bar_without_a_core_to_the_search():
    bar = np.zeros((300, 400), dtype=bool)
    bar[165:215, 150:300] = True
    region = _disc(150, 165, 50) | _disc(230, 135, 50) | bar        # a cloud
    ps = parts(region)
    assert len(ps) == 2
    left = (region & ~np.logical_or(*ps)).sum()
    assert left > 0.5 * bar[:, 280:].sum()              # the bar's far end is in no part
    assert np.logical_or(*parts(region, whole=True)).sum() == region.sum()


def test_parts_of_one_shape_are_none():
    bar = np.zeros((300, 400), dtype=bool)
    bar[100:150, 50:350] = True
    assert parts(_disc(200, 150, 80)) == [] and parts(bar) == []


def test_add_parts_draws_each_disc_on_its_own():
    # two circles stacked on a stadium: one shape over both circles fixes
    # more pixels than either, so the greedy search takes it and patches
    stadium = Shape(100, 100, 200, 100, 1, radii=(50,) * 4)
    circles = [Shape(150, 50, 100, 100, 2, ell=True), Shape(150, 150, 100, 100, 2, ell=True)]
    T = render_labels(0, [stadium] + circles)
    shapes = add_parts(T, 0, [stadium], 2, parts(T == 2))
    assert len(shapes) == 3 and error(T, 0, shapes) < 100
    assert sorted((s.x, s.y, s.w, s.h) for s in shapes[1:]) == [(150, 50, 100, 100), (150, 150, 100, 100)]

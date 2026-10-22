import numpy as np

from cssynth.motifs import mirrored, nest, symmetries, turned
from cssynth.search import extract_palette
from cssynth.shapes import Shape, render_labels
from cssynth.simplify import _plainer


def test_mirror_of_a_leaf_draws_the_mirror_image():
    s = Shape(60, 80, 80, 80, 1, radii=(80, 0, 80, 0), rot=30)
    a = render_labels(0, [s])
    b = render_labels(0, [mirrored(s, "x", 200)])
    assert (a[:, ::-1] == b).mean() > 0.999          # equal up to edge rounding


def test_quarter_turns_of_a_box_stay_unturned():
    s = Shape(50, 40, 60, 30, 1, radii=(10, 0, 0, 0))
    t = turned(s, 200, 150, 90)
    assert not t.rot and (t.w, t.h) == (30, 60) and t.radii == (0, 10, 0, 0)
    assert render_labels(0, [turned(t, 200, 150, 270)]).tolist() == render_labels(0, [s]).tolist()


def test_nest_peels_concentric_rings():
    rings = [Shape(80, 40, 220, 220, 1, ell=True), Shape(95, 55, 190, 190, 2, ell=True),
             Shape(110, 70, 160, 160, 0, ell=True)]
    T = render_labels(0, rings)
    layers = nest(T, T == 1)
    assert [c for c, _ in layers] == [1, 2, 0]
    for (c, m), s in zip(layers, rings):
        assert abs(int(m.sum()) - int((render_labels(-1, [s]) >= 0).sum())) < 0.01 * m.sum()


def test_symmetries_find_turns_and_mirrors():
    # four leaves turned about a point: a pinwheel, so turns but no mirror
    petals = [turned(Shape(200, 120, 60, 60, 1, radii=(60, 0, 60, 0)), 200, 150, 90 * k) for k in range(4)]
    kinds = {(k, p[2] if k == "turns" else p[0]) for k, p, _ in symmetries(render_labels(0, petals) == 1)}
    assert ("turns", 4) in kinds and not any(k == "mirror" for k, _ in kinds)
    leaf = Shape(60, 100, 80, 80, 1, radii=(80, 0, 80, 0), rot=45)
    pair = render_labels(0, [leaf, mirrored(leaf, "x", 200)])
    assert ("mirror", ("x", 200.0)) in {(k, (p[0], float(p[1]))) for k, p, _ in symmetries(pair == 1) if k == "mirror"}


def test_plainer_squares_corners_one_at_a_time():
    s = Shape(0, 0, 50, 50, 1, radii=(4, 0, 2, 0))
    assert [t.radii for t in _plainer(s)] == [(0, 0, 0, 0), (0, 0, 2, 0), (4, 0, 0, 0)]
    assert list(_plainer(Shape(0, 0, 50, 50, 1, ell=True))) == []


def test_palette_merges_a_shade_off_color():
    img = np.zeros((300, 400, 3), dtype=np.uint8)
    img[:] = (238, 184, 80)
    img[50:150, 50:150] = (101, 146, 207)
    img[50:150, 200:300] = (101, 146, 206)          # how a turned copy of it is painted
    pal, labels = extract_palette(img)
    assert len(pal) == 2 and labels[100, 100] == labels[100, 250]

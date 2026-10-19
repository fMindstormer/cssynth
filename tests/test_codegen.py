import numpy as np

from cssynth.codegen import bgcolor_attr, color_css, emit, gradient_css, num, px, radius_css, reused_clip
from cssynth.shapes import Gradient, Shape


def test_color_css_picks_shortest_spelling():
    assert color_css((255, 0, 0)) == "red"
    assert color_css((0xd2, 0xb4, 0x8c)) == "tan"
    assert color_css((0x11, 0x22, 0x33)) == "#123"
    assert color_css((0x5d, 0x3a, 0x3a)) == "#5d3a3a"


def test_bgcolor_attr_accepts_bare_hex():
    assert bgcolor_attr((0x5d, 0x3a, 0x3a)) == "5d3a3a"
    assert bgcolor_attr((255, 0, 0)) == "red"


def test_num_drops_leading_zero_and_trailing_decimals():
    assert num(50) == "50"
    assert num(50.0) == "50"
    assert num(0.5) == ".5"
    assert num(-0.5) == "-.5"
    assert num(12.25) == "12.25"


def test_px_omits_unit_for_zero():
    assert px(0) == "0"
    assert px(25) == "25px"


def test_radius_css():
    assert radius_css(Shape(0, 0, 100, 60, 1, ell=True)) == "50%"
    assert radius_css(Shape(0, 0, 100, 100, 1)) is None
    # a saturated radius on a square: 50px, 50% and 4em all draw a circle
    assert len(radius_css(Shape(0, 0, 100, 100, 1, radii=(50,) * 4))) == 3


def test_alike_elements_share_a_tag():
    # two rounded petals at different angles plus two unrelated boxes: the
    # petals share size, corners and color under their own tag and rule
    pal = np.array([(255, 255, 255), (109, 72, 10), (20, 90, 160)])
    shapes = [Shape(10, 10, 30, 40, 2), Shape(300, 200, 60, 20, 2),
              Shape(150, 100, 100, 100, 1, radii=(100, 0, 100, 0), rot=45),
              Shape(150, 100, 100, 100, 1, radii=(100, 0, 100, 0), rot=-45)]
    code, _ = emit(pal, 0, shapes)
    assert code.count(radius_css(shapes[2])) == 1
    assert "i{position:fixed" in code or "u{position:fixed" in code or "s{position:fixed" in code


def test_soft_gradient_stops_are_placed_exactly():
    pal = np.array([(0, 0, 0), (255, 0, 0), (0, 0, 128)])
    hard = Gradient(90.0, ((1, 100.0), (2, 400.0)))
    soft = Gradient(90.0, ((1, 100.0), (2, 400.0)), (1.0,))
    assert gradient_css(hard, pal) == "linear-gradient(90deg,red 25%,navy 0)"
    assert gradient_css(soft, pal) == "linear-gradient(90deg,red 99.5px,navy 100.5px)"


def test_mirrored_polygon_reuses_the_clip_path():
    pal = np.array([(250, 240, 220), (30, 60, 120)])
    a = Shape.polygon([(10, 10), (60, 10), (40, 50), (20, 30)], 1)
    for fx, fy, scale in [(True, False, "-1 1"), (False, True, "1 -1"), (True, True, "-1")]:
        b = a.flipped(fx, fy).moved(200, 100)
        assert reused_clip(a, b) == scale
        code, _ = emit(pal, 0, [a, b])
        assert code.count("polygon(") == 1 and f"scale:{scale}" in code
    assert reused_clip(a, a.moved(5, 5)) == ""
    assert reused_clip(a, Shape.polygon([(10, 10), (60, 10), (41, 50), (20, 30)], 1)) is None

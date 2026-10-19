import numpy as np

from cssynth.codegen import bgcolor_attr, color_css, emit, num, px, radius_css
from cssynth.shapes import Shape


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

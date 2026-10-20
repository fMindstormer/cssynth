"""End to end: draw a target, compile it, check the code and the internal render."""
import numpy as np
from PIL import Image, ImageDraw

from cssynth import compile_image
from cssynth.shapes import Shape, render_rgb


def compile_drawing(tmp_path, bg, rects=(), polys=()):
    img = Image.new("RGB", (400, 300), bg)
    d = ImageDraw.Draw(img)
    for box, color in rects:
        d.rectangle([box[0], box[1], box[2] - 1, box[3] - 1], fill=color)
    for pts, color in polys:
        d.polygon(pts, fill=color)
    path = tmp_path / "target.png"
    img.save(path)
    return compile_image(path)


def test_single_box(tmp_path):
    code, info, _ = compile_drawing(tmp_path, "#5d3a3a", rects=[((0, 0, 200, 200), "#b5e0ba")])
    assert info["wrong_px"] == 0
    assert code == '<body bgcolor=5d3a3a><b style="position:fixed;inset:0 200px 100px 0;background:#b5e0ba">'


def test_repeated_boxes_become_shadows(tmp_path):
    squares = [((x, y, x + 50, y + 50), "#fdc57b") for x in (50, 300) for y in (50, 200)]
    code, info, _ = compile_drawing(tmp_path, "#62374e", rects=squares)
    assert info["wrong_px"] == 0
    assert info["elements"] == 1 and info["shadows"] == 3
    assert len(code) <= 155


def test_concave_polygon_is_one_shape(tmp_path):
    notched = [(150, 50), (205, 50), (250, 95), (250, 150), (195, 150), (150, 105)]
    code, info, (_, _, _, shapes) = compile_drawing(tmp_path, "#d669ec", polys=[(notched, "#fdfbf8")])
    assert len(shapes) == 1 and shapes[0].poly is not None
    assert info["wrong_px"] < 150
    assert len(code) < 200


def test_leaf_is_one_turned_shape(tmp_path):
    pal = np.array([(146, 105, 39), (255, 255, 255)])
    leaf = Shape(150, 100, 100, 100, 1, radii=(100, 0, 100, 0), rot=135)
    path = tmp_path / "leaf.png"
    Image.fromarray(render_rgb(0, pal, [leaf])).save(path)
    code, info, (_, _, _, shapes) = compile_image(path)
    assert len(shapes) == 1 and shapes[0].rot and any(shapes[0].radii)
    assert info["wrong_px"] < 500           # the curved edges' antialiasing, mostly
    assert len(code) < 140


def test_parallel_variants_give_the_same_code(tmp_path):
    img = Image.new("RGB", (400, 300), "#62374e")
    d = ImageDraw.Draw(img)
    d.ellipse([100, 50, 199, 149], fill="#fdc57b")
    d.polygon([(250, 200), (350, 200), (300, 120)], fill="#fdc57b")
    path = tmp_path / "t.png"
    img.save(path)
    serial = compile_image(path, research=False)[0]
    assert compile_image(path, research=False, jobs=3)[0] == serial

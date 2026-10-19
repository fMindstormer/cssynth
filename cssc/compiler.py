"""Compile a target image: run every search variant, simplify, keep the best."""

import numpy as np
from PIL import Image

from .codegen import emit
from .search import decompose
from .shapes import render_rgb
from .simplify import simplify

# Search settings tried per image: (pixels a shape must fix, starts per
# color, always climb from bounding boxes, base layer, outline polygons).
# Higher thresholds give fewer, cheaper shapes; the bounding-box starts find
# bars inside compound regions but can lead the greedy search down a longer
# path; a gradient base helps striped pictures; outline polygons fit concave
# and many-sided figures in one shape, but the greedy search can also take
# them where boxes and shadows would be shorter, so they run as extra
# variants. Every variant is simplified and scored by the same objective, and
# the best one wins.
VARIANTS = [(25, 3, True, "flat", False), (80, 3, True, "flat", False),
            (25, 3, False, "flat", False), (80, 3, False, "flat", False),
            (25, 3, True, "gradient", False), (80, 3, False, "gradient", False),
            (25, 3, True, "flat", True), (80, 3, True, "flat", True),
            (25, 3, True, "gradient", True)]

# The objective everything is scored by: characters + wrong pixels / RHO.
# RHO is how many wrong pixels we accept to save one character. At 0.5 the
# length-aware clean-up costs no match on the benchmark; larger values golf
# harder (see bench/tradeoff.py).
RHO = 0.5


def compile_image(path, log=None, variants=VARIANTS, rho=RHO):
    img = Image.open(path).convert("RGB")
    if img.size != (400, 300):
        img = img.resize((400, 300), Image.BOX)
    arr = np.asarray(img)
    runs = []
    for min_gain, per_color, bbox_starts, base, outlines in variants:
        out = decompose(arr, log=log, min_gain=min_gain, per_color=per_color,
                        bbox_starts=bbox_starts, base=base, outlines=outlines)
        if out is None:          # no gradient fits this picture
            continue
        pal, bg, T, shapes = out
        shapes = simplify(T, bg, pal, shapes, rho=rho, log=log)
        code, info = emit(pal, bg, shapes)
        sim = render_rgb(bg, pal, shapes)
        wrong = int((np.abs(sim.astype(int) - arr.astype(int)).max(2) > 8).sum())
        J = len(code) + wrong / rho
        runs.append((J, code, {**info, "wrong_px": wrong, "J": round(J, 1),
                               "variant": [min_gain, per_color, bbox_starts, base, outlines]},
                     (pal, bg, T, shapes)))
    _, code, info, model = min(runs, key=lambda r: r[0])
    return code, info, model

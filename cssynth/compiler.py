"""Compile a target image: run every search variant, simplify, keep the best."""

from concurrent.futures import ProcessPoolExecutor

import numpy as np
from PIL import Image

from .codegen import emit
from .improve import improve
from .search import decompose
from .shapes import render_rgb
from .simplify import simplify

# Search settings tried per image: (pixels a shape must fix, starts per
# color, always climb from bounding boxes, base layer, outline polygons).
# Higher thresholds give fewer, cheaper shapes; one search serves several
# thresholds (see search.greedy). The bounding-box starts find bars inside
# compound regions but can lead the greedy search down a longer path; a
# gradient base helps striped pictures; outline polygons fit concave and
# many-sided figures in one shape, but the greedy search can also take them
# where boxes and shadows would be shorter, so they run as extra variants.
# Every result is simplified and scored by the same objective, and the best
# one wins.
VARIANTS = [((25, 80), 3, True, "flat", False), ((25,), 3, False, "flat", False),
            ((25,), 3, True, "gradient", False), ((80,), 3, False, "gradient", False),
            ((25, 80), 3, True, "flat", True), ((25,), 3, True, "gradient", True)]

# The objective everything is scored by: characters + wrong pixels / RHO.
# RHO is how many wrong pixels we accept to save one character. At 0.5 the
# length-aware clean-up costs no match on the benchmark; larger values golf
# harder (see bench/tradeoff.py).
RHO = 0.5


def _finish(arr, rho, pal, bg, shapes):
    """(J, code, info) of a stack, scored against the target image."""
    code, info = emit(pal, bg, shapes)
    sim = render_rgb(bg, pal, shapes)
    wrong = int((np.abs(sim.astype(int) - arr.astype(int)).max(2) > 8).sum())
    J = len(code) + wrong / rho
    return J, code, {**info, "wrong_px": wrong, "J": round(J, 1)}


def _run_variant(arr, variant, rho, log=None):
    """Search, simplify and score one variant: [(J, code, info, model), ...]."""
    min_gains, per_color, bbox_starts, base, outlines = variant
    out = decompose(arr, log=log, min_gains=min_gains, per_color=per_color,
                    bbox_starts=bbox_starts, base=base, outlines=outlines)
    if out is None:              # no gradient fits this picture
        return []
    pal, bg, T, stacks = out
    runs = []
    for min_gain, shapes in stacks.items():
        shapes = simplify(T, bg, pal, shapes, rho=rho, log=log)
        J, code, info = _finish(arr, rho, pal, bg, shapes)
        runs.append((J, code, {**info, "variant": [min_gain, per_color, bbox_starts, base, outlines]},
                     (pal, bg, T, shapes)))
    return runs


def compile_image(image, log=None, variants=VARIANTS, rho=RHO, research=True, jobs=1):
    """image: a path or a PIL image. research: re-search parts of the best
    result (see improve). jobs: processes to run the variants in (the
    result is the same for any number)."""
    img = (image if isinstance(image, Image.Image) else Image.open(image)).convert("RGB")
    if img.size != (400, 300):
        img = img.resize((400, 300), Image.BOX)
    arr = np.asarray(img)

    if jobs > 1:
        with ProcessPoolExecutor(min(jobs, len(variants))) as ex:
            per_variant = list(ex.map(_run_variant, *zip(*[(arr, v, rho) for v in variants])))
    else:
        per_variant = [_run_variant(arr, v, rho, log) for v in variants]
    runs = [run for rs in per_variant for run in rs]
    J, code, info, (pal, bg, T, shapes) = min(runs, key=lambda r: r[0])
    if research:
        min_gain, per_color, bbox_starts, _, outlines = info["variant"]
        better = improve(lambda sh: _finish(arr, rho, pal, bg, sh)[0], pal, bg, T, shapes, rho,
                         min_gain, per_color, bbox_starts, outlines, log=log)
        if better is not shapes:
            J2, code, info2 = _finish(arr, rho, pal, bg, better)
            info = {**info2, "variant": info["variant"], "researched": round(J - J2, 1)}
            shapes = better
    return code, info, (pal, bg, T, shapes)

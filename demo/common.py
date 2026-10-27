"""Shared by the demos (the Gradio app and the in-browser page): prepare an
uploaded picture, compile it, and summarize the result."""

import base64
import io
import time

import numpy as np
from PIL import Image

from cssynth import compile_image
from cssynth.search import extract_palette
from cssynth.shapes import render_rgb

MAX_COLORS = 8          # more colors than this and the picture isn't flat: reduce it first


def flatten(img: Image.Image) -> tuple[Image.Image, list[str]]:
    """Fit the picture to CSSBattle's 400x300 frame and, if it has many
    colors (a photo, a screenshot with gradients), reduce it to a few.
    Returns the picture the compiler gets and what was done to it."""
    img = img.convert("RGB")
    notes = []
    if img.size != (400, 300):
        img = img.resize((400, 300), Image.BOX)
        notes.append("Resized to 400×300")
    arr = np.asarray(img)
    # flat targets have a few colors plus antialiasing blends (the benchmark's
    # have at most 823 distinct colors and 4 real ones); photos have thousands
    if len(np.unique(arr.reshape(-1, 3), axis=0)) > 2000 or len(extract_palette(arr)[0]) > MAX_COLORS:
        img = img.quantize(MAX_COLORS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).convert("RGB")
        notes.append("Reduced to eight colors (cssynth is made for flat pictures)")
    return img, notes


def compiler_name() -> str:
    """Which shadow grouping this environment runs: OR-Tools has no browser build."""
    try:
        import ortools  # noqa: F401
        return "full compiler (OR-Tools shadow grouping)"
    except ImportError:
        return "browser build (greedy shadow grouping, no OR-Tools)"


def png_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def compile_picture(image: Image.Image, research=False, rho=0.5, jobs=1) -> dict:
    """Compile an uploaded picture; returns the code, the exact target it was
    compiled from (as a PNG data URL) and a few numbers. estimated_match
    compares cssynth's internal rasterizer with that target; it is not a
    measurement of a browser render (the benchmark measures Chromium renders)."""
    img, notes = flatten(image)
    t = time.time()
    code, info, (pal, bg, _, shapes) = compile_image(img, rho=rho, research=research, jobs=jobs)
    target = np.asarray(img).astype(int)
    match = float((np.abs(render_rgb(bg, pal, shapes).astype(int) - target).max(2) <= 8).mean() * 100)
    return {"code": code, "chars": len(code), "estimated_match": round(match, 2), "elements": info["elements"],
            "shadows": info["shadows"], "seconds": round(time.time() - t, 1), "notes": notes,
            "target": png_data_url(img), "compiler": compiler_name(),
            "settings": {"research": bool(research), "rho": rho}}

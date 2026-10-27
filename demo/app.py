"""cssynth demo: upload a flat picture, get short HTML/CSS that draws it.

    pip install gradio -e ..   &&   python app.py

The same demo runs in the browser from web/ (see README.md here).
"""

import base64
import io
import os
from pathlib import Path
from urllib.parse import quote

import gradio as gr
from common import compile_picture
from PIL import Image

EXAMPLES = sorted(str(p) for p in (Path(__file__).parent / "examples").glob("*.png"))


def preview(code: str) -> str:
    """The generated code, rendered by the visitor's own browser. A data: URL
    rather than srcdoc, since srcdoc documents never use quirks mode, and
    the code relies on it for unitless lengths."""
    return (f'<iframe src="data:text/html;charset=utf-8,{quote(code)}" width="400" height="300" '
            'style="border:1px solid #8884;display:block;background:#fff" '
            'title="The generated code, rendered by your browser"></iframe>')


def run(image, research, rho):
    if image is None:
        raise gr.Error("Upload a picture or pick an example first.")
    r = compile_picture(image, research=research, rho=rho, jobs=os.cpu_count() or 1)
    notes = "".join(f"**{n}.** " for n in r["notes"])
    stats = (f"{notes}**{r['chars']} characters** ({r['elements']} elements, {r['shadows']} box-shadows), "
             f"{r['seconds']:.0f} s, {r['compiler']}.\n\n"
             f"Estimated match — internal renderer: {r['estimated_match']:.2f}%. This compares cssynth's own "
             "rasterizer (its search model) with the compiled target, not the browser preview; benchmark "
             "scores come from Chromium renders.")
    compiled = Image.open(io.BytesIO(base64.b64decode(r["target"].split(",", 1)[1])))
    return r["code"], preview(r["code"]), stats, compiled


with gr.Blocks(title="cssynth") as demo:
    gr.Markdown(
        "# cssynth\n"
        "Compile a flat picture into short HTML/CSS for "
        "[CSSBattle](https://cssbattle.dev): boxes, circles, rotated shapes, `clip-path` "
        "polygons, gradients and box-shadows, chosen to minimize characters. "
        "[Source, method and benchmark](https://github.com/fMindstormer/cssynth).")
    with gr.Row():
        with gr.Column():
            image = gr.Image(type="pil", label="Target (400×300, flat colors)", image_mode="RGB", format="png")
            research = gr.Checkbox(label="Re-search the result (slower, shorter code)", value=False)
            rho = gr.Slider(0.25, 4, value=0.5, step=0.25, label="ρ: wrong pixels accepted per character saved")
            go = gr.Button("Compile", variant="primary")
            compiled = gr.Image(type="pil", label="Compiled target: exactly the picture cssynth compiled",
                                interactive=False, format="png")
        with gr.Column():
            stats = gr.Markdown()
            rendered = gr.HTML(label="Rendered by your browser")
            code = gr.Code(language="html", label="Generated code", wrap_lines=True, lines=4, max_lines=12)
    if EXAMPLES:
        gr.Examples(EXAMPLES, inputs=image, label="Targets from the benchmark (OmPreetham/cssbattle, MIT)")
    go.click(run, [image, research, rho], [code, rendered, stats, compiled])

if __name__ == "__main__":
    demo.queue(default_concurrency_limit=1).launch()

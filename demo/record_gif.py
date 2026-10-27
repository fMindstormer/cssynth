"""Turn the frames from record.js into docs/demo.gif, with a caption under
each frame. The last frame shows the downloaded file rendered on its own next
to the target, instead of the page.

    python record_gif.py frames/ ../docs/demo.gif
"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 820                 # the GIF's width; frames are scaled to it
BAR = 44                    # caption bar height
HERE = Path(__file__).parent


def font(size):
    for name in ["/System/Library/Fonts/Supplemental/Arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]:
        if Path(name).exists():
            return ImageFont.truetype(name, size)
    return ImageFont.load_default()


def side_by_side(alone, target, h):
    """The downloaded file's render and the target, 400x300 each."""
    pad = 20
    im = Image.new("RGB", (WIDTH, h), "#f1f2f4")
    d = ImageDraw.Draw(im)
    w = (WIDTH - 3 * pad) // 2
    for i, (src, label) in enumerate([(target, "Target"), (alone, "Downloaded file, opened on its own")]):
        pic = Image.open(src).convert("RGB").resize((w, w * 3 // 4), Image.LANCZOS)
        x = pad + i * (w + pad)
        y = (h - pic.height) // 2
        im.paste(pic, (x, y))
        d.text((x, y - 28), label, fill="#17181c", font=font(18))
    return im


def main():
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    frames = json.loads((src / "frames.json").read_text())
    images, durations = [], []
    for f in frames:
        page = Image.open(src / f["file"]).convert("RGB")
        page = page.resize((WIDTH, page.height * WIDTH // page.width), Image.LANCZOS)
        if f.get("alone"):
            page = side_by_side(src / f["alone"], HERE / "examples" / f["target"], page.height)
        im = Image.new("RGB", (WIDTH, page.height + BAR), "#17181c")
        im.paste(page, (0, 0))
        ImageDraw.Draw(im).text((16, page.height + 12), f["caption"], fill="#ffffff", font=font(18))
        images.append(im.quantize(64, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE))
        durations.append(int(f["seconds"] * 1000))
    images[0].save(out, save_all=True, append_images=images[1:], duration=durations, loop=0, optimize=True)
    print(f"wrote {out}: {len(images)} frames, {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()

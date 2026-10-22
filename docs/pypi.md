# cssynth

A compiler from images to short HTML/CSS. It is aimed at
[CSSBattle](https://cssbattle.dev) targets: flat 400×300 pictures that players
redraw in as few characters as they can.

![cssynth's 214-character output for a CSSBattle-style target: a dark red arch on red](https://raw.githubusercontent.com/fMindstormer/cssynth/main/bench/out/om-20240318.png)

On a benchmark of 66 targets rendered in Chromium, cssynth's code is shorter
than the (minified, not golfed) human solution on 56, with all 66 at a 99%+
pixel match.

```sh
pip install cssynth
cssynth target.png           # prints the code; length and details on stderr
cssynth --fast target.png    # skip the re-search: about 2x faster, longer code
```

```python
from cssynth import compile_image
code, info, model = compile_image("target.png")
```

- [Try it in your browser](https://fmindstormer.github.io/cssynth/demo/)
- [Benchmark results](https://fmindstormer.github.io/cssynth/)
- [How it works](https://fmindstormer.github.io/cssynth/blog/), and the [method in detail](https://github.com/fMindstormer/cssynth/blob/main/docs/method.md)
- [Source](https://github.com/fMindstormer/cssynth)

MIT licensed. Not affiliated with CSSBattle.

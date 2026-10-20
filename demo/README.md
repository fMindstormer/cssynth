# cssynth demos

Two ways to try cssynth on a picture without the command line:

- **In the browser** (`web/`): a static page that runs cssynth with
  [Pyodide](https://pyodide.org), published at
  https://fmindstormer.github.io/cssynth/demo/. The Pages workflow builds a
  cssynth wheel from the same commit and serves it next to the page.
  OR-Tools has no browser build, so this version uses the greedy box-shadow
  grouping, and compiling takes about a minute. Nothing is uploaded.
- **Locally with Gradio** (`app.py`): the same interface with the full
  compiler, using all cores:

  ```sh
  pip install gradio -e ..
  python app.py
  ```

`common.py` is shared by both: it fits an upload to 400×300, reduces
pictures that aren't flat to a few colors, compiles, and summarizes the
result.

The example targets in `examples/` are Chromium renders of solutions from
[OmPreetham/cssbattle](https://github.com/OmPreetham/cssbattle), MIT
License, Copyright (c) 2024 Om Preetham Bandi; see `examples/LICENSE`.
Not affiliated with CSSBattle.

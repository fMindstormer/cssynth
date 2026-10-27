# cssynth demos

Two ways to try cssynth on a picture without the command line:

- **In the browser** (`web/`): a static page that runs cssynth with
  [Pyodide](https://pyodide.org), published at
  https://fmindstormer.github.io/cssynth/demo/. The Pages workflow builds a
  cssynth wheel from the same commit and serves it next to the page.
  OR-Tools has no browser build, so this version uses the greedy box-shadow
  grouping, and compiling takes from about 10 seconds to two minutes on a
  laptop. Nothing is uploaded.
- **Locally with Gradio** (`app.py`): the same interface with the full
  compiler, using all cores:

  ```sh
  pip install gradio -e ..
  python app.py
  ```

`common.py` is shared by both: it fits an upload to 400×300, reduces
pictures that aren't flat to eight colors, compiles, and summarizes the
result. It returns the exact picture it compiled, which the page shows as the
target, with notices for what was changed. The match it reports is an
estimate from cssynth's internal rasterizer, labeled as such; benchmark
scores come from Chromium renders.

## The browser page

- **Saved results.** Three examples (`examples/saved.json`) show at once,
  before Python has loaded: a clean success, one that reuses shapes with
  box-shadows, and a limitation (rotated wedges and a circle, drawn with
  visible facets). `save_examples.py` makes them with the page's default
  settings and the browser build's grouping, and measures each on a Chromium
  render; compiling them again in the browser gives the same code.
- **Runs.** Inputs and settings are locked while compiling, and each result
  carries the id of its run, so a result is never shown beside a target it
  wasn't compiled from. Cancel terminates the worker (a running Python call
  can't be interrupted) and starts a new one. If Python fails to load or a
  compile fails, Retry starts again.
- **Download HTML** saves the exact generated document: no doctype is added,
  so it opens in quirks mode like CSSBattle's frame.

To run the page locally, assemble the site the way the Pages workflow does
and serve it:

```sh
mkdir -p site/demo && cp web/* common.py site/demo/ && cp -r examples site/demo/
pip wheel .. --no-deps -w site/demo && (cd site/demo && ls *.whl > wheel.txt)
python -m http.server -d site 8000        # http://localhost:8000/demo/
```

**Browser checks** (`check.js`): a saved result before Python loads; a
fresh compile, its download opened on its own (byte for byte the code, quirks
mode, ≥ 99% match at 400×300); cancel and compile again; inputs locked and a
stale answer ignored; files that can't be read; Python failing to load, then
Retry. The Pages workflow runs them before publishing.

```sh
npm ci --prefix ../bench
NODE_PATH=../bench/node_modules CHROME_PATH=/path/to/chrome node check.js http://localhost:8000/demo/
```

`record.js` and `record_gif.py` make the recording in the main README
(`docs/demo.gif`).

The example targets in `examples/` are Chromium renders of solutions from
[OmPreetham/cssbattle](https://github.com/OmPreetham/cssbattle), MIT
License, Copyright (c) 2024 Om Preetham Bandi; see `examples/LICENSE`.
Not affiliated with CSSBattle.

// Runs cssynth in the browser: Pyodide (Python compiled to WebAssembly) with
// numpy, scipy and Pillow, plus the cssynth wheel built by the Pages workflow.
// The page talks to this worker with messages, so compiling never blocks it.

import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs";

const status = (text) => postMessage({ type: "status", text });

async function setup() {
  status("Loading Python (about 30 MB, once)…");
  const py = await loadPyodide();
  status("Loading numpy, scipy and Pillow…");
  await py.loadPackage(["numpy", "scipy", "pillow", "micropip"]);
  status("Installing cssynth…");
  const wheel = (await (await fetch("wheel.txt")).text()).trim();
  // OR-Tools has no browser build; cssynth falls back to its greedy shadow grouping.
  await py.pyimport("micropip").install.callKwargs(new URL(wheel, self.location).href, { deps: false });
  py.FS.writeFile("common.py", await (await fetch("common.py")).text());
  await py.runPythonAsync(`
import io, json
from PIL import Image
from common import compile_picture

def run(data, research, rho):
    image = Image.open(io.BytesIO(bytes(data)))
    return json.dumps(compile_picture(image, research=research, rho=rho))
`);
  return py;
}

const ready = setup().then(
  (py) => { postMessage({ type: "ready" }); return py; },
  (err) => { postMessage({ type: "error", message: String(err) }); throw err; },
);

onmessage = async ({ data }) => {
  try {
    const py = await ready;
    const out = py.globals.get("run")(new Uint8Array(data.image), data.research, data.rho);
    postMessage({ type: "result", ...JSON.parse(out) });
  } catch (err) {
    postMessage({ type: "error", message: String(err) });
  }
};

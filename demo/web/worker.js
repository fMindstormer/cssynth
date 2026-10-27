// Runs cssynth in the browser: Pyodide (Python compiled to WebAssembly) with
// numpy, scipy and Pillow, plus the cssynth wheel built by the Pages workflow.
// The page talks to this worker with messages, so compiling never blocks it.
// A compile is one synchronous Python call, so a message can't interrupt it:
// the page cancels by terminating this worker and starting a new one.
//
//   page -> worker  {id, image, research, rho}
//   worker -> page  {type: "status", text}            while loading
//                   {type: "ready"}                   loaded
//                   {type: "fatal", message}          loading failed; start a new worker
//                   {type: "result", id, ...}         a compile finished (or input_error)
//                   {type: "error", id, message}      a compile raised; the worker still works

import { loadPyodide } from "https://cdn.jsdelivr.net/pyodide/v314.0.7/full/pyodide.mjs";

const status = (text) => postMessage({ type: "status", text });

async function setup() {
  status("Loading Python (about 30 MB, once)…");
  const py = await loadPyodide();
  status("Loading numpy, scipy and Pillow…");
  await py.loadPackage(["numpy", "scipy", "pillow", "micropip"]);
  status("Installing cssynth…");
  const wheel = (await fetchOk("wheel.txt").then((r) => r.text())).trim();
  // OR-Tools has no browser build; cssynth falls back to its greedy shadow grouping.
  await py.pyimport("micropip").install.callKwargs(new URL(wheel, self.location).href, { deps: false });
  py.FS.writeFile("common.py", await fetchOk("common.py").then((r) => r.text()));
  await py.runPythonAsync(`
import io, json
from PIL import Image
from common import compile_picture

def run(data, research, rho):
    try:
        image = Image.open(io.BytesIO(bytes(data)))
        image.load()
    except Exception as e:
        return json.dumps({"input_error": f"cssynth couldn't read this file as a picture ({type(e).__name__}). Choose another."})
    return json.dumps(compile_picture(image, research=research, rho=rho))
`);
  return py;
}

async function fetchOk(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r;
}

const ready = setup().then(
  (py) => { postMessage({ type: "ready" }); return py; },
  (err) => { postMessage({ type: "fatal", message: String(err) }); return null; },
);

onmessage = async ({ data }) => {
  const py = await ready;
  if (!py) return;                      // already reported as fatal
  try {
    const out = py.globals.get("run")(new Uint8Array(data.image), data.research, data.rho);
    postMessage({ type: "result", id: data.id, ...JSON.parse(out) });
  } catch (err) {
    // a Python traceback: its last line says what went wrong
    postMessage({ type: "error", id: data.id, message: String(err).trim().split("\n").pop() });
  }
};

// Browser checks for the in-browser demo: what a visitor does, in Chromium.
//
//   node check.js http://localhost:8000/demo/        (NODE_PATH=../bench/node_modules)
//
// The site is the one the Pages workflow assembles (web/, common.py,
// examples/ and a wheel; see README.md). Checks:
//   saved      a saved result is on screen before Python has loaded
//   compile    a fresh compile, its code rendered in a 400x300 frame, and the
//              downloaded file: byte for byte the code, no doctype, and it
//              draws the target when opened on its own
//   cancel     cancel a long compile, the worker restarts, compile again
//   pairing    inputs locked while compiling, a stale answer is ignored, and
//              a new pick clears the old result
//   invalid    a file the browser can't read, then one only Python can't read
//   restart    Python fails to load (blocked wheel), Retry recovers
// Chrome: CHROME_PATH, or the runner's google-chrome.
const fs = require("fs");
const os = require("os");
const path = require("path");
const puppeteer = require("puppeteer-core");

const URL_ = process.argv[2] || "http://localhost:8000/demo/";
const LOAD = 300_000, COMPILE = 300_000;
const results = [];
let browser;

async function check(name, fn) {
  const t = Date.now();
  try {
    await fn();
    results.push([name, "ok", Date.now() - t]);
    console.log(`ok    ${name} (${((Date.now() - t) / 1000).toFixed(0)} s)`);
  } catch (e) {
    results.push([name, "FAIL", Date.now() - t]);
    console.log(`FAIL  ${name}: ${e.message}`);
  }
}

function assert(cond, msg) { if (!cond) throw new Error(msg); }

async function open(block) {
  const page = await browser.newPage();
  await page.setViewport({ width: 1100, height: 1000 });
  page.on("pageerror", (e) => console.log("  page error:", e.message));
  if (block) {
    await page.setRequestInterception(true);
    page.on("request", (r) => (block.on && r.url().endsWith(block.on) ? r.abort() : r.continue()));
  }
  await page.goto(URL_);
  return page;
}

const text = (page, sel) => page.$eval(sel, (e) => e.textContent);
const visible = (page, sel) => page.$eval(sel, (e) => !e.hidden);
const waitReady = (page) => page.waitForFunction(() => !document.getElementById("go").disabled, { timeout: LOAD });
const waitStatus = (page, re, timeout = COMPILE) =>
  page.waitForFunction((s) => new RegExp(s).test(document.getElementById("status").textContent), { timeout }, re.source);
const waitFresh = (page) =>
  page.waitForFunction(() => { const b = document.getElementById("badge"); return !b.hidden && b.textContent.startsWith("Fresh result"); },
                      { timeout: COMPILE });

async function pickSaved(page, i) {
  await page.evaluate((i) => document.querySelectorAll("#saved button")[i].click(), i);
  await page.waitForFunction((i) => document.querySelectorAll("#saved button")[i].getAttribute("aria-pressed") === "true", {}, i);
}

// the share of pixels within 8 levels of the target, of a 400x300 screenshot
async function matchTarget(page, png, target) {
  return page.evaluate(async (shot, target) => {
    const load = (src) => new Promise((ok, err) => { const i = new Image(); i.onload = () => ok(i); i.onerror = err; i.src = src; });
    const px = (img) => { const c = new OffscreenCanvas(400, 300); const g = c.getContext("2d"); g.drawImage(img, 0, 0); return g.getImageData(0, 0, 400, 300).data; };
    const a = px(await load("data:image/png;base64," + shot)), b = px(await load(target));
    let good = 0;
    for (let i = 0; i < a.length; i += 4) {
      if (Math.max(Math.abs(a[i] - b[i]), Math.abs(a[i + 1] - b[i + 1]), Math.abs(a[i + 2] - b[i + 2])) <= 8) good++;
    }
    return (100 * good) / (400 * 300);
  }, Buffer.from(png).toString("base64"), target);
}

async function renderAlone(url) {
  const p = await browser.newPage();
  await p.setViewport({ width: 400, height: 300 });
  await p.goto(url);
  const quirks = await p.evaluate(() => document.compatMode);
  const png = await p.screenshot({ clip: { x: 0, y: 0, width: 400, height: 300 } });
  await p.close();
  return { png, quirks };
}

(async () => {
  browser = await puppeteer.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    args: ["--disable-gpu", "--force-color-profile=srgb", "--font-render-hinting=none"],
    protocolTimeout: 600_000,
  });
  const dl = fs.mkdtempSync(path.join(os.tmpdir(), "cssynth-dl-"));

  await check("saved", async () => {
    const page = await open();
    await page.waitForFunction(() => document.getElementById("badge").textContent.startsWith("Saved result"), { timeout: 10_000 });
    assert(await page.$eval("#go", (b) => b.disabled), "Compile should wait for Python");
    assert((await text(page, "#code")).length > 50, "no saved code");
    assert(await page.$("#out-frame iframe"), "no preview of the saved code");
    assert((await text(page, "#stats")).includes("Estimated match — internal renderer"), "estimate not labeled");
    assert((await text(page, "#stats")).includes("Measured on a Chromium render"), "no Chromium measurement for the saved result");
    await page.close();
  });

  let page;
  await check("compile", async () => {
    page = await open();
    await waitReady(page);
    await pickSaved(page, 0);
    assert((await text(page, "#go")) === "Compile again", "saved example should offer Compile again");
    await page.click("#go");
    await waitFresh(page);
    const code = await text(page, "#code");
    assert(code.length > 50, "empty code");
    assert((await text(page, "#target-caption")).startsWith("Compiled target"), "target isn't labeled as the compiled one");
    // the preview iframe holds the same code
    const src = await page.$eval("#out-frame iframe", (f) => decodeURIComponent(f.src.split(",").slice(1).join(",")));
    assert(src === code, "preview iframe doesn't hold the shown code");
    // download it, and open the file on its own at 400x300
    const cdp = await page.createCDPSession();
    await cdp.send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: dl });
    await page.click("#download");
    const file = path.join(dl, "cssynth-om-20240318.html");
    for (let i = 0; i < 50 && !fs.existsSync(file); i++) await new Promise((r) => setTimeout(r, 100));
    const bytes = fs.readFileSync(file, "utf8");
    assert(bytes === code, "the downloaded file isn't exactly the generated code");
    assert(!/^\s*<!doctype/i.test(bytes), "a doctype was added");
    const alone = await renderAlone("file://" + file);
    assert(alone.quirks === "BackCompat", `the file opens in ${alone.quirks}, not quirks mode`);
    const m = await matchTarget(page, alone.png, new URL("examples/om-20240318.png", URL_).href);
    assert(m >= 99, `the downloaded file draws the target at ${m.toFixed(2)}%`);
    console.log(`      downloaded file: ${bytes.length} characters, quirks mode, ${m.toFixed(2)}% match at 400x300`);
  });

  await check("cancel", async () => {
    await pickSaved(page, 2);                       // the slowest saved example
    await page.click("#go");
    await waitStatus(page, /Compiling… [2-9]/, 30_000);
    await page.click("#cancel");
    assert(/Restarting Python/.test(await text(page, "#status")), "no restarting notice");
    assert(await page.$eval("#go", (b) => b.disabled), "Compile enabled before the new worker is ready");
    assert((await text(page, "#badge")).startsWith("Saved result"), "the saved result wasn't restored");
    await waitReady(page);
    await pickSaved(page, 0);
    await page.click("#go");
    await waitFresh(page);
    assert((await text(page, "#code")).length > 50, "no result after cancelling");
  });

  await check("pairing", async () => {
    await pickSaved(page, 0);
    await page.click("#go");
    await waitStatus(page, /Compiling/, 10_000);
    const locked = await page.evaluate(() =>
      [...document.querySelectorAll("#file, .setting, .examples button")].every((e) => e.disabled));
    assert(locked, "inputs aren't locked while compiling");
    // an answer to some other run must not be shown
    await page.evaluate(() => handle({ type: "result", id: -1, code: "<p>stale", chars: 8, estimated_match: 1, elements: 1,
                                        shadows: 0, seconds: 0, notes: [], target: "", compiler: "", settings: {} }));
    assert(!(await text(page, "#code")).includes("stale"), "a stale result was shown");
    assert(/Compiling/.test(await text(page, "#status")), "a stale result ended the run");
    await waitFresh(page);
    // a new pick clears the old result
    await page.evaluate(() => document.querySelector("#examples button").click());
    await page.waitForFunction(() => document.getElementById("badge").hidden, { timeout: 5_000 });
    assert(await visible(page, "#codebox") === false, "old code still shown beside a new target");
    assert((await text(page, "#target-caption")).includes("not compiled yet"), "new target not labeled as uncompiled");
  });

  await check("invalid", async () => {
    const bad = path.join(dl, "notes.png");
    fs.writeFileSync(bad, "not a picture");
    await (await page.$("#file")).uploadFile(bad);
    await waitStatus(page, /isn't a picture your browser can read/, 10_000);
    // an SVG: the browser can show it, Pillow can't read it
    const svg = path.join(dl, "shape.svg");
    fs.writeFileSync(svg, '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="300"><rect width="200" height="100" fill="red"/></svg>');
    await (await page.$("#file")).uploadFile(svg);
    await page.waitForFunction(() => document.getElementById("target-caption").textContent.includes("not compiled yet"));
    await page.click("#go");
    await waitStatus(page, /couldn't read this file as a picture/, COMPILE);
    assert(await page.$eval("#file", (e) => !e.disabled), "inputs still locked after the error");
    assert(!(await visible(page, "#cancel")), "Cancel still shown after the error");
    await pickSaved(page, 0);
    await page.click("#go");
    await waitFresh(page);
  });
  await page?.close();

  await check("restart", async () => {
    const block = { on: "wheel.txt" };
    const p = await open(block);
    await waitStatus(p, /Python couldn't load/, LOAD);
    assert(await visible(p, "#retry"), "no Retry after a failed load");
    assert((await text(p, "#badge")).startsWith("Saved result"), "the saved result disappeared");
    block.on = null;
    await p.click("#retry");
    await waitReady(p);
    await p.click("#go");
    await waitFresh(p);
    await p.close();
  });

  await browser.close();
  const failed = results.filter((r) => r[1] !== "ok").length;
  console.log(failed ? `${failed} of ${results.length} checks failed` : `all ${results.length} checks passed`);
  process.exit(failed ? 1 : 0);
})();

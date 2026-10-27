// Record the demo for the README: pick a target, compile, look at the code,
// download it and open the file on its own. Writes numbered frames and
// captions; record_gif.py turns them into docs/demo.gif. Waits are cut, and
// the caption says so and how long they really took.
//
//   node record.js http://localhost:8000/demo/ frames/      (NODE_PATH=../bench/node_modules)
const fs = require("fs");
const os = require("os");
const path = require("path");
const puppeteer = require("puppeteer-core");

const [URL_, OUT] = [process.argv[2], process.argv[3]];
const TARGET = 1;          // "More targets": the green I-beam
fs.mkdirSync(OUT, { recursive: true });
const frames = [];
let page;

async function frame(caption, seconds = 1.2, shot = null) {
  const file = path.join(OUT, `${String(frames.length).padStart(3, "0")}.png`);
  if (shot) fs.writeFileSync(file, shot);
  else await page.screenshot({ path: file });
  frames.push({ file: path.basename(file), caption, seconds });
}

async function point(selector) {
  // headless screenshots have no cursor: ring what is about to be clicked
  await page.$eval(selector, (e) => { e.style.outline = "3px solid #e0457b"; e.style.outlineOffset = "3px"; });
}
async function unpoint(selector) { await page.$eval(selector, (e) => { e.style.outline = ""; }); }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    args: ["--disable-gpu", "--force-color-profile=srgb"], protocolTimeout: 600_000,
  });
  page = await browser.newPage();
  await page.setViewport({ width: 1100, height: 1060 });
  await page.emulateMediaFeatures([{ name: "prefers-color-scheme", value: "light" }]);
  const t0 = Date.now();
  await page.goto(URL_);
  await page.waitForFunction(() => !document.getElementById("badge").hidden);
  await sleep(500);
  await page.evaluate(() => scrollTo(0, 280));
  await frame("A saved result is on screen at once, while Python loads", 2.5);
  await page.waitForFunction(() => !document.getElementById("go").disabled, { timeout: 300_000 });
  await frame(`Python ready (waiting cut: it took ${Math.round((Date.now() - t0) / 1000)} s)`, 1.5);

  const pick = `#examples button:nth-child(${TARGET + 1})`;
  await point(pick); await frame("Pick a target", 1.2);
  await unpoint(pick);
  await page.click(pick);
  await sleep(300);
  await point("#go"); await frame("Compile, in the browser", 1.2);
  await unpoint("#go");
  await page.click("#go");
  const t1 = Date.now();
  for (let i = 0; i < 3; i++) { await sleep(1000); await frame("Compiling…", 0.7); }
  await page.waitForFunction(() => { const b = document.getElementById("badge"); return !b.hidden && b.textContent.startsWith("Fresh"); },
                             { timeout: 300_000 });
  const took = Math.round((Date.now() - t1) / 1000);
  const chars = await page.$eval("#code", (e) => e.textContent.length);
  await frame(`Done (waiting cut: compiling took ${took} s)`, 2.5);
  await page.evaluate(() => document.getElementById("stats").scrollIntoView({ block: "start" }));
  await sleep(300);
  await frame(`${chars} characters of HTML/CSS, and the estimate labeled as an estimate`, 3);

  const dl = fs.mkdtempSync(path.join(os.tmpdir(), "cssynth-rec-"));
  const cdp = await page.createCDPSession();
  await cdp.send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: dl });
  await point("#download"); await frame("Download HTML: the exact generated document", 1.8);
  await unpoint("#download");
  await page.click("#download");
  let file = null;
  for (let i = 0; i < 50 && !file; i++) { await sleep(100); file = fs.readdirSync(dl).find((f) => f.endsWith(".html")); }
  // the downloaded file on its own, at the 400x300 size CSSBattle uses
  const alone = await browser.newPage();
  await alone.setViewport({ width: 400, height: 300 });
  await alone.goto("file://" + path.join(dl, file));
  const mode = await alone.evaluate(() => document.compatMode);
  const shot = await alone.screenshot();
  fs.writeFileSync(path.join(OUT, "alone.png"), shot);
  await frame(`${file} opened on its own at 400×300 (${mode === "BackCompat" ? "quirks mode" : mode}), next to the target`, 4,
              await page.screenshot());
  frames[frames.length - 1].alone = "alone.png";
  frames[frames.length - 1].target = await page.evaluate((i) => new URL(document.querySelectorAll("#examples img")[i].src).pathname.split("/").pop(), TARGET);
  fs.writeFileSync(path.join(OUT, "frames.json"), JSON.stringify(frames, null, 1));
  console.log(`${frames.length} frames; compiled ${chars} characters in ${took} s`);
  await browser.close();
})();

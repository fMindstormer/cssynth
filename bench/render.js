// Render HTML snippets the way CSSBattle does: a 400x300 frame, no doctype
// (quirks mode), default browser styles.
//
//   node render.js jobs.json
// jobs.json: [{html, out}]  -> writes a 400x300 PNG per job.
const fs = require('fs');
const path = require('path');
const chromium = require(process.env.CHROMIUM_PKG || '@sparticuz/chromium');
const puppeteer = require(process.env.PUPPETEER_PKG || 'puppeteer-core');

(async () => {
  const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const browser = await puppeteer.launch({
    executablePath: await chromium.executablePath(),
    args: [...chromium.args, '--font-render-hinting=none', '--force-color-profile=srgb'],
    headless: true,
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 400, height: 300, deviceScaleFactor: 1 });
  await page.setRequestInterception(true);
  page.on('request', r => (r.url().startsWith('data:') ? r.continue() : r.abort()));
  let done = 0;
  for (const job of jobs) {
    try {
      await page.setContent(job.html, { waitUntil: 'load', timeout: 10000 });
      await page.screenshot({ path: job.out, clip: { x: 0, y: 0, width: 400, height: 300 } });
      done++;
    } catch (e) {
      console.error('render failed', job.out, e.message);
    }
  }
  await browser.close();
  console.log(`rendered ${done}/${jobs.length}`);
})();

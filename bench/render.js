// Render HTML snippets the way CSSBattle does: a 400x300 frame, no doctype
// (quirks mode), default browser styles.
//
//   node render.js jobs.json
// jobs.json: [{html, out}]  -> writes a 400x300 PNG per job.
//
// Chromium: @sparticuz/chromium (Linux x64, the build the targets were made
// with), or any Chrome given by CHROME_PATH, e.g. Chrome for Testing 131:
//   npx @puppeteer/browsers install chrome@131.0.6778.204
// Other platforms render edges slightly differently (about 0.2% of pixels on
// average against the Linux targets).
const fs = require('fs');
const puppeteer = require('puppeteer-core');

async function launchOptions() {
  const flags = ['--font-render-hinting=none', '--force-color-profile=srgb'];
  if (process.env.CHROME_PATH) {
    return { executablePath: process.env.CHROME_PATH, args: ['--disable-gpu', ...flags] };
  }
  const chromium = require('@sparticuz/chromium');
  return { executablePath: await chromium.executablePath(), args: [...chromium.args, ...flags] };
}

(async () => {
  const jobs = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const browser = await puppeteer.launch({ ...(await launchOptions()), headless: true });
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

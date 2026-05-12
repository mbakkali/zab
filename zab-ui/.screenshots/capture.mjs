import { chromium } from '@playwright/test';
const url = process.argv[2] || 'http://127.0.0.1:8742/';
const out = process.argv[3] || '.screenshots/full.png';
const click = process.argv[4];
const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const page = await ctx.newPage();
await page.goto(url, { waitUntil: 'networkidle' });
if (click) {
  try {
    await page.getByRole('button', { name: new RegExp(click, 'i') }).first().click({ timeout: 4000 });
    await page.waitForTimeout(700);
  } catch (e) { console.error('button click failed', click, e.message); }
}
await page.screenshot({ path: out, fullPage: true });
await browser.close();
console.log('saved', out);

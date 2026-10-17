// Temporary research probe run on a GitHub runner (open egress).
import { chromium } from 'playwright';
const T = 'https://www.trip.com/flights/showfarefirst?';
const tail = '&class=y&quantity=1&locale=zh-TW&curr=TWD';
const SEGS = [['hkg','tpe','hkg','tpe'],['tpe','tyo','tpe','nrt'],['tyo','tpe','nrt','tpe'],['tpe','hkg','tpe','hkg']];
const cities = SEGS.map(([dc, ac, da, aa], i) => `dcity${i}=${dc}&acity${i}=${ac}&dairport${i}=${da}&aairport${i}=${aa}`).join('&');
const dates = (base, ds) => ds.map((d, i) => `ddate${i + base}=${d}`).join('&');
const FEB = ['2027-02-05', '2027-02-06', '2027-02-17', '2027-02-24'];
const GAP = ['2027-02-05', '2027-02-06', '2027-02-17', '2027-06-10'];
const CLOSE = ['2027-02-05', '2027-02-06', '2027-02-08', '2027-02-10'];
const LINKS = {
  d1_close: `${T}triptype=mt&${cities}&${dates(1, CLOSE)}${tail}`,
  d0_close: `${T}triptype=mt&${cities}&${dates(0, CLOSE)}${tail}`,
  d1_feb: `${T}triptype=mt&${cities}&${dates(1, FEB)}${tail}`,
};
const browser = await chromium.launch({ args: ['--disable-blink-features=AutomationControlled'] });
const ctx = await browser.newContext({ locale: 'en-US', userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36', viewport: { width: 1366, height: 1000 } });
for (const [name, url] of Object.entries(LINKS)) {
  const page = await ctx.newPage();
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(16000);
    const ds = await page.evaluate(() => [...document.querySelectorAll('[data-testid*="date" i], .city-date')].map(e => `${e.getAttribute('data-testid') || 'city-date'}=${(e.getAttribute('aria-label') || e.value || e.textContent || '').replace(/\s+/g, ' ').trim()}`).filter(s => /\d/.test(s)));
    console.log(`#### ${name} | title=${await page.title()} | dates=${JSON.stringify(ds)} | url=${page.url()}`);
    const segs = await page.evaluate(() => [...document.querySelectorAll('[data-testid*="city" i], [class*="city-name" i]')].map(e => (e.getAttribute('aria-label') || e.value || e.textContent || '').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 20));
    console.log(`#### ${name} cities=${JSON.stringify(segs)}`);
    const btn = page.locator('button:has-text("Search"), [data-testid*="search" i] button, [class*="search-btn" i]').first();
    if (await btn.count()) { await btn.click({ timeout: 5000 }).catch(e => console.log('click fail ' + e)); await page.waitForTimeout(8000); console.log(`#### ${name} after-search url=${page.url()}`); }
    const hrefs = await page.evaluate(() => [...document.querySelectorAll('a[href*="triptype"]')].map(a => a.href).slice(0, 3));
    console.log(`#### ${name} hrefs=${JSON.stringify(hrefs)}`);
  } catch (e) { console.log(`#### FAIL ${name} ${e}`); }
  await page.close();
}
await browser.close();

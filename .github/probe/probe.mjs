// Temporary research probe run on a GitHub runner (open egress).
import { chromium } from 'playwright';
const T = 'https://www.trip.com/flights/showfarefirst?';
const tail = '&class=y&quantity=1&locale=zh-TW&curr=TWD';
const SEGS = [['hkg','tpe','hkg','tpe'],['tpe','tyo','tpe','nrt'],['tyo','tpe','nrt','tpe'],['tpe','hkg','tpe','hkg']];
const cities = SEGS.map(([dc, ac, da, aa], i) => `dcity${i}=${dc}&acity${i}=${ac}&dairport${i}=${da}&aairport${i}=${aa}`).join('&');
const dates = (base, ds) => ds.map((d, i) => `ddate${i + base}=${d}`).join('&');
const FEB = ['2027-02-05', '2027-02-06', '2027-02-17', '2027-02-24'];
const GAP = ['2027-02-05', '2027-02-06', '2027-02-17', '2027-06-10'];
const LINKS = {
  dates0_feb: `${T}triptype=mt&${cities}&${dates(0, FEB)}${tail}`,
  dates1_feb: `${T}triptype=mt&${cities}&${dates(1, FEB)}${tail}`,
  dates0_gap: `${T}triptype=mt&${cities}&${dates(0, GAP)}${tail}`,
  comma_dates: `${T}triptype=mt&${cities}&ddate=${GAP.join(',')}${tail}`,
  ow_rmq: `${T}dcity=rmq&acity=hkg&dairport=rmq&aairport=hkg&ddate=2027-03-10&triptype=ow${tail}`,
};
const browser = await chromium.launch({ args: ['--disable-blink-features=AutomationControlled'] });
const ctx = await browser.newContext({ locale: 'en-US', userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36', viewport: { width: 1366, height: 1000 } });
for (const [name, url] of Object.entries(LINKS)) {
  const page = await ctx.newPage();
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(16000);
    const ds = await page.evaluate(() => [...document.querySelectorAll('[data-testid*="date" i], .city-date')].map(e => `${e.getAttribute('data-testid') || 'city-date'}=${(e.getAttribute('aria-label') || e.value || e.textContent || '').replace(/\s+/g, ' ').trim()}`).filter(s => /\d/.test(s)));
    console.log(`#### ${name} | title=${await page.title()} | dates=${JSON.stringify(ds)} | mt2rt=${page.url().includes('mt2rt')}`);
  } catch (e) { console.log(`#### FAIL ${name} ${e}`); }
  await page.close();
}
for (const [name, tfs] of [['google_rt', 'GhoSCjIwMjctMDItMDVqBRIDVFBFcgUSA05SVBoaEgoyMDI3LTAyLTE1agUSA05SVHIFEgNUUEVCAQFIAZgBAQ=='], ['google_ow', 'GhoSCjIwMjctMDItMDNqBRIDVFBFcgUSA0hLR0IBAUgBmAEC']]) {
  const g = await ctx.newPage();
  await g.goto(`https://www.google.com/travel/flights?tfs=${encodeURIComponent(tfs)}&hl=zh-TW&curr=TWD`, { waitUntil: 'domcontentloaded' });
  await g.waitForTimeout(9000);
  const text = (await g.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ');
  console.log(`#### ${name} | title=${await g.title()} | inputs=${JSON.stringify(await g.evaluate(() => [...document.querySelectorAll('input')].map(i => i.value).filter(Boolean).slice(0, 6)))} | text=${text.slice(0, 300)}`);
}
await browser.close();

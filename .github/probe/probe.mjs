// Temporary research probe run on a GitHub runner (open egress).
import { chromium } from 'playwright';
const T = 'https://www.trip.com/flights/showfarefirst?';
const tail = '&class=y&quantity=1&locale=zh-TW&curr=TWD';
const idx = (segs, airports) => segs.map(([dc, ac, d, da, aa], i) =>
  `dcity${i}=${dc}&acity${i}=${ac}&ddate${i}=${d}` + (airports ? `&dairport${i}=${da}&aairport${i}=${aa}` : '')).join('&');
const FOUR = [['hkg','tpe','2027-02-05','hkg','tpe'],['tpe','tyo','2027-02-05','tpe','nrt'],['tyo','tpe','2027-02-17','nrt','tpe'],['tpe','hkg','2027-06-10','tpe','hkg']];
const FOUR_DISTINCT = [['hkg','tpe','2027-02-05','hkg','tpe'],['tpe','tyo','2027-02-06','tpe','nrt'],['tyo','tpe','2027-02-17','nrt','tpe'],['tpe','hkg','2027-06-10','tpe','hkg']];
const TWO = [['tyo','tpe','2027-02-15','nrt','tpe'],['tpe','tyo','2027-06-10','tpe','nrt']];
const LINKS = {
  mt_four_sameday_airports: `${T}triptype=mt&${idx(FOUR, true)}${tail}`,
  mt_four_distinct_airports: `${T}triptype=mt&${idx(FOUR_DISTINCT, true)}${tail}`,
  mt_four_distinct_cities: `${T}triptype=mt&${idx(FOUR_DISTINCT, false)}${tail}`,
  mt_two_airports: `${T}triptype=mt&${idx(TWO, true)}${tail}`,
};
const browser = await chromium.launch();
const ctx = await browser.newContext({ locale: 'en-US', userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36', viewport: { width: 1366, height: 1000 } });
for (const [name, url] of Object.entries(LINKS)) {
  const page = await ctx.newPage();
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(20000);
    const segs = await page.evaluate(() => [...document.querySelectorAll('li.m-searchForm__item, .m-searchForm__segment')].map(e => e.innerText.replace(/\s+/g, ' ')).filter(Boolean).slice(0, 8));
    const dates = await page.evaluate(() => [...document.querySelectorAll('input')].filter(i => /date|Return/i.test(i.getAttribute('aria-label') || '')).map(i => `${i.getAttribute('aria-label')}=${i.value}`));
    const text = (await page.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ');
    const at = text.indexOf('Multi-city');
    console.log(`\n######## ${name}\nfinal=${page.url()}\ntitle=${await page.title()}\nsegments=${JSON.stringify(segs)}\ndates=${JSON.stringify(dates)}\ntext=${text.slice(at, at + 1800)}\n######## END`);
  } catch (e) { console.log(`FAIL ${name} ${e}`); }
  await page.close();
}
await browser.close();

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
  dates1_gap: `${T}triptype=mt&${cities}&${dates(1, GAP)}${tail}`,
  two_dates1: `${T}triptype=mt&dcity0=tpe&acity0=tyo&dairport0=tpe&aairport0=nrt&dcity1=osa&acity1=tpe&dairport1=kix&aairport1=tpe&ddate1=2027-02-05&ddate2=2027-06-10${tail}`,
};
// city codes for the catalog's non-city-code airports
for (const [city, apt] of [['sel','icn'],['spk','cts'],['lon','lhr'],['par','cdg'],['nyc','jfk'],['txg','rmq'],['osa','kix'],['tyo','hnd'],['ngo','ngo'],['oka','oka']]) {
  LINKS[`ow_${apt}`] = `${T}dcity=tpe&acity=${city}&dairport=tpe&aairport=${apt}&ddate=2027-03-10&triptype=ow${tail}`;
}
const browser = await chromium.launch({ args: ['--disable-blink-features=AutomationControlled'] });
const ctx = await browser.newContext({ locale: 'en-US', userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36', viewport: { width: 1366, height: 1000 } });
for (const [name, url] of Object.entries(LINKS)) {
  const page = await ctx.newPage();
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(name.startsWith('ow_') ? 9000 : 16000);
    const ds = await page.evaluate(() => [...document.querySelectorAll('[data-testid^="search_date_depart"]')].map(e => `${e.getAttribute('data-testid').slice(-1)}=${e.innerText.trim()}`));
    const segs = await page.evaluate(() => [...document.querySelectorAll('[aria-label^="Departure airport or city"], [aria-label^="Arrival airport or city"]')].map(e => e.getAttribute('aria-label').replace(/^(Departure|Arrival) airport or city /, '')).slice(0, 8));
    console.log(`#### ${name} | title=${await page.title()} | dates=${JSON.stringify(ds)} | cities=${JSON.stringify(segs)} | mt2rt=${page.url().includes('mt2rt')}`);
  } catch (e) { console.log(`#### FAIL ${name} ${e}`); }
  await page.close();
}
// Google single-ticket q= link
const g = await ctx.newPage();
await g.goto('https://www.google.com/travel/flights?q=' + encodeURIComponent('Flights from TPE to NRT on 2027-02-05 through 2027-02-15 1 adult economy') + '&hl=zh-TW&curr=TWD', { waitUntil: 'domcontentloaded' });
await g.waitForTimeout(8000);
console.log(`#### google_q | title=${await g.title()} | inputs=${JSON.stringify(await g.evaluate(() => [...document.querySelectorAll('input')].map(i => i.value).filter(Boolean).slice(0, 6)))}`);
await browser.close();

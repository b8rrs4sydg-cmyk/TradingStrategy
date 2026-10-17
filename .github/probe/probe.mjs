// Temporary research probe (deleted after use): Trip.com multi-city in a
// Taiwan-like browser, and Google Flights result-label format for parsing.
import { chromium } from 'playwright';
const MT4 = 'triptype=mt&dcity0=hkg&acity0=tpe&dairport0=hkg&aairport0=tpe&dcity1=tpe&acity1=tyo&dairport1=tpe&aairport1=nrt&dcity2=tyo&acity2=tpe&dairport2=nrt&aairport2=tpe&dcity3=tpe&acity3=hkg&dairport3=tpe&aairport3=hkg&ddate1=2027-02-05&ddate2=2027-02-05&class=y&quantity=1&locale=zh-TW&curr=TWD';
const OJ2 = 'triptype=mt&dcity0=tpe&acity0=osa&dairport0=tpe&aairport0=kix&dcity1=tyo&acity1=tpe&dairport1=nrt&aairport1=tpe&ddate1=2027-02-03&ddate2=2027-04-05&class=y&quantity=1&locale=zh-TW&curr=TWD';
const browser = await chromium.launch({ args: ['--disable-blink-features=AutomationControlled'] });
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36';
const tw = await browser.newContext({ locale: 'zh-TW', timezoneId: 'Asia/Taipei', userAgent: UA, viewport: { width: 1366, height: 1000 }, extraHTTPHeaders: { 'Accept-Language': 'zh-TW,zh;q=0.9' } });
async function trip(name, url) {
  const page = await tw.newPage();
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(15000);
    const info = await page.evaluate(() => ({
      dates: [...document.querySelectorAll('[data-testid*="date" i]')].map(e => `${e.getAttribute('data-testid')}=${(e.getAttribute('aria-label') || e.value || e.textContent || '').trim()}`).filter(s => /\d/.test(s)),
      tabs: [...document.querySelectorAll('[role=tab], [role=radio], label, li')].map(e => e.textContent.trim()).filter(t => /單程|來回|多|One|Round|Multi/.test(t) && t.length < 20).slice(0, 10),
      checked: [...document.querySelectorAll('[aria-checked=true], [aria-selected=true], .active, .is-active')].map(e => e.textContent.trim()).filter(t => t && t.length < 20).slice(0, 10),
      buttons: [...document.querySelectorAll('button, [role=button]')].map(b => (b.textContent || b.getAttribute('aria-label') || '').trim()).filter(t => t && t.length < 25).slice(0, 40),
      testids: [...new Set([...document.querySelectorAll('[data-testid]')].map(e => e.getAttribute('data-testid')))].filter(t => /search|seg|trip|mt|multi/i.test(t)).slice(0, 40),
    }));
    console.log(`#### ${name} | url=${page.url()} | title=${await page.title()} | ${JSON.stringify(info)}`);
    const btn = page.locator('[data-testid*="search_btn" i], [data-testid*="searchBtn" i], button:has-text("搜尋"), button:has-text("Search")').first();
    if (await btn.count()) {
      await btn.click({ timeout: 5000 }).catch(e => console.log('click fail ' + e));
      await page.waitForTimeout(10000);
      console.log(`#### ${name} after-search url=${page.url()}`);
    } else console.log(`#### ${name} no search button`);
  } catch (e) { console.log(`#### FAIL ${name} ${e}`); }
  await page.close();
}
await trip('www_mt4', `https://www.trip.com/flights/showfarefirst?${MT4}`);
await trip('tw_mt4', `https://tw.trip.com/flights/showfarefirst?${MT4}`);
await trip('tw_oj2', `https://tw.trip.com/flights/showfarefirst?${OJ2}`);
// Trip.com multi-city search page: does it have its own path?
await trip('tw_multicity_home', 'https://tw.trip.com/flights/?triptype=mt&locale=zh-TW&curr=TWD');

// Google Flights result labels (en-US, TWD) for parsing
const en = await browser.newContext({ locale: 'en-US', userAgent: UA });
const G = {
  rt: 'GhoSCjIwMjctMDItMDVqBRIDVFBFcgUSA05SVBoaEgoyMDI3LTAyLTE1agUSA05SVHIFEgNUUEVCAQFIAZgBAQ==',
  ow: 'GhoSCjIwMjctMDItMDNqBRIDVFBFcgUSA0hLR0IBAUgBmAEC',
  mc: 'GhoSCjIwMjctMDItMDVqBRIDSEtHcgUSA1RQRRoaEgoyMDI3LTAyLTA1agUSA1RQRXIFEgNOUlQaGhIKMjAyNy0wMi0xN2oFEgNOUlRyBRIDVFBFGhoSCjIwMjctMDQtMDNqBRIDVFBFcgUSA0hLR0IBAUgBmAED',
};
for (const [name, tfs] of Object.entries(G)) {
  const g = await en.newPage();
  const t0 = Date.now();
  await g.goto(`https://www.google.com/travel/flights?tfs=${encodeURIComponent(tfs)}&hl=en&gl=TW&curr=TWD`, { waitUntil: 'domcontentloaded' });
  await g.waitForSelector('li div[aria-label*="dollars"], li [aria-label*="TWD"]', { timeout: 20000 }).catch(() => {});
  const labels = await g.evaluate(() => [...document.querySelectorAll('li div[aria-label]')].map(e => e.getAttribute('aria-label')).filter(a => /dollar|TWD|NT\$/i.test(a)).slice(0, 4));
  const blocks = await g.evaluate(() => [...document.querySelectorAll('li')].map(li => li.innerText.replace(/\s+/g, ' ')).filter(t => /NT\$|TWD|\$\d/.test(t)).slice(0, 3));
  console.log(`#### google_${name} ms=${Date.now() - t0} labels=${JSON.stringify(labels)} blocks=${JSON.stringify(blocks)}`);
  await g.close();
}
await browser.close();

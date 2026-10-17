// Temporary research probe (deleted after use): mirrored 2-segment multi-city links.
import { chromium } from 'playwright';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36';
const browser = await chromium.launch({ args: ['--disable-blink-features=AutomationControlled'] });
const tw = await browser.newContext({ locale: 'zh-TW', timezoneId: 'Asia/Taipei', userAgent: UA, viewport: { width: 1366, height: 1000 } });
const T = 'https://tw.trip.com/flights/showfarefirst?';
const tail = '&triptype=mt&class=y&quantity=1&searchboxarg=t&nonstoponly=off&locale=zh-TW&curr=TWD';
const LINKS = {
  mirrored: T + 'multdcity0=tyo&multacity0=tpe&dairport0=nrt&aairport0=tpe&multddate0=2027-02-15&multdcity1=tpe&multacity1=tyo&dairport1=tpe&aairport1=nrt&multddate1=2027-04-03' + tail,
  wrap: T + 'multdcity0=tpe&multacity0=tyo&dairport0=tpe&aairport0=nrt&multddate0=2027-02-05&multdcity1=tyo&multacity1=tpe&dairport1=nrt&aairport1=tpe&multddate1=2027-04-11' + tail,
};
for (const [name, url] of Object.entries(LINKS)) {
  const page = await tw.newPage();
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(15000);
    const info = await page.evaluate(() => ({
      dates: [...document.querySelectorAll('[data-testid^="search_date"]')].map(e => `${e.getAttribute('data-testid')}=${(e.getAttribute('aria-label') || e.value || e.textContent || '').trim()}`),
      mode: [...document.querySelectorAll('[data-testid^="tripType_radio"]')].map(e => `${e.getAttribute('data-testid')}:${e.className.toString().includes('radio_selected')}`),
      price: (document.body.innerText.match(/TWD[\d,]+/g) || []).slice(0, 3),
    }));
    console.log(`#### ${name} | url=${page.url().slice(0, 160)} | mt2rt=${page.url().includes('mt2rt')} | ${JSON.stringify(info)}`);
  } catch (e) { console.log(`#### FAIL ${name} ${e}`); }
  await page.close();
}
const en = await browser.newContext({ locale: 'en-US', userAgent: UA });
const g = await en.newPage();
await g.goto('https://www.google.com/travel/flights?tfs=' + encodeURIComponent('GhoSCjIwMjctMDItMTVqBRIDTlJUcgUSA1RQRRoaEgoyMDI3LTA0LTAzagUSA1RQRXIFEgNOUlRCAQFIAZgBAw==') + '&hl=en&gl=TW&curr=TWD', { waitUntil: 'domcontentloaded' });
const ok = await g.waitForSelector("li div[aria-label*='New Taiwan dollars']", { timeout: 45000 }).then(() => true).catch(() => false);
const text = (await g.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ');
console.log(`#### google_mirrored ok=${ok} text=${text.slice(150, 650)}`);
await browser.close();

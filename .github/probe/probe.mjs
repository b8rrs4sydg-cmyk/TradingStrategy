// Temporary research probe (deleted after use): mirrored 2-segment multi-city links.
import { chromium } from 'playwright';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36';
const browser = await chromium.launch({ args: ['--disable-blink-features=AutomationControlled'] });
const tw = await browser.newContext({ locale: 'zh-TW', timezoneId: 'Asia/Taipei', userAgent: UA, viewport: { width: 1366, height: 1000 } });
const T = 'https://tw.trip.com/flights/showfarefirst?';
const tail = '&triptype=mt&class=y&quantity=1&searchboxarg=t&nonstoponly=off&locale=zh-TW&curr=TWD';
const LINKS = {
  mt2rt0: T + 'multdcity0=tyo&multacity0=tpe&dairport0=nrt&aairport0=tpe&multddate0=2027-02-15&multdcity1=tpe&multacity1=tyo&dairport1=tpe&aairport1=nrt&multddate1=2027-04-03' + tail + '&mt2rt=0',
  mt2rtfalse: T + 'multdcity0=tyo&multacity0=tpe&dairport0=nrt&aairport0=tpe&multddate0=2027-02-15&multdcity1=tpe&multacity1=tyo&dairport1=tpe&aairport1=nrt&multddate1=2027-04-03' + tail + '&mt2rt=false',
  searchform: T + 'multdcity0=tyo&multacity0=tpe&dairport0=nrt&aairport0=tpe&multddate0=2027-02-15&multdcity1=tpe&multacity1=tyo&dairport1=tpe&aairport1=nrt&multddate1=2027-04-03' + tail + '&lowpricesource=searchform',
  cityonly: T + 'multdcity0=tyo&multacity0=tpe&multddate0=2027-02-15&multdcity1=tpe&multacity1=tyo&multddate1=2027-04-03' + tail,
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
await browser.close();

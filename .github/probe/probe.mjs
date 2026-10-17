// Temporary research probe (deleted after use).
import { chromium } from 'playwright';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36';
const browser = await chromium.launch({ args: ['--disable-blink-features=AutomationControlled'] });
const tw = await browser.newContext({ locale: 'zh-TW', timezoneId: 'Asia/Taipei', userAgent: UA, viewport: { width: 1366, height: 1000 } });
const segs = [['hkg','tpe','hkg','tpe','2027-02-05'],['tpe','tyo','tpe','nrt','2027-02-05'],['tyo','tpe','nrt','tpe','2027-02-16'],['tpe','hkg','tpe','hkg','2027-04-03']];
const mult = (ids) => segs.map(([dc, ac, da, aa, d], i) => `multdcity${i}=${dc}&multacity${i}=${ac}` + (ids ? `&multdcityid${i}=${ids[dc]}&multacityid${i}=${ids[ac]}` : '') + `&dairport${i}=${da}&aairport${i}=${aa}&multddate${i}=${d}`).join('&');
const tail = '&triptype=mt&class=y&quantity=1&searchboxarg=t&nonstoponly=off&locale=zh-TW&curr=TWD';
const LINKS = {
  tw_noids: `https://tw.trip.com/flights/showfarefirst?${mult(null)}${tail}`,
  www_noids: `https://www.trip.com/flights/showfarefirst?${mult(null)}${tail}`,
  tw_ids: `https://tw.trip.com/flights/showfarefirst?${mult({ hkg: 58, tpe: 617, tyo: 228 })}${tail}`,
  tw_rt: 'https://tw.trip.com/flights/showfarefirst?dcity=tpe&acity=tyo&dairport=tpe&aairport=nrt&ddate=2027-02-05&rdate=2027-02-15&triptype=rt&class=y&quantity=1&locale=zh-TW&curr=TWD',
};
for (const [name, url] of Object.entries(LINKS)) {
  const page = await tw.newPage();
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(15000);
    const info = await page.evaluate(() => ({
      dates: [...document.querySelectorAll('[data-testid^="search_date"]')].map(e => `${e.getAttribute('data-testid')}=${(e.getAttribute('aria-label') || e.value || e.textContent || '').trim()}`),
      from: [...document.querySelectorAll('[data-testid^="search_city_from"]:not([data-testid$="wrapper"]), [data-testid^="search_city_to"]:not([data-testid$="wrapper"])')].map(e => `${e.getAttribute('data-testid')}=${(e.value || e.textContent || '').trim().slice(0, 30)}`),
      mode: [...document.querySelectorAll('[data-testid^="tripType_radio"]')].map(e => `${e.getAttribute('data-testid')}:${e.getAttribute('aria-checked') || e.className.toString().slice(0, 40)}`),
      price: (document.body.innerText.match(/TWD[\d,]+/g) || []).slice(0, 3),
    }));
    console.log(`#### ${name} | url=${page.url().slice(0, 140)} | ${JSON.stringify(info)}`);
  } catch (e) { console.log(`#### FAIL ${name} ${e}`); }
  await page.close();
}
const G = {
  rt: 'GhoSCjIwMjctMDItMDVqBRIDVFBFcgUSA05SVBoaEgoyMDI3LTAyLTE1agUSA05SVHIFEgNUUEVCAQFIAZgBAQ==',
  mc: 'GhoSCjIwMjctMDItMDVqBRIDSEtHcgUSA1RQRRoaEgoyMDI3LTAyLTA1agUSA1RQRXIFEgNOUlQaGhIKMjAyNy0wMi0xN2oFEgNOUlRyBRIDVFBFGhoSCjIwMjctMDQtMDNqBRIDVFBFcgUSA0hLR0IBAUgBmAED',
};
for (const [lang, extra] of [['en', '&hl=en&curr=TWD'], ['en_gl', '&hl=en&gl=TW&curr=TWD'], ['zh', '&hl=zh-TW&curr=TWD']]) {
  const ctx = await browser.newContext({ locale: lang.startsWith('zh') ? 'zh-TW' : 'en-US', userAgent: UA });
  for (const [name, tfs] of Object.entries(G)) {
    const g = await ctx.newPage();
    const t0 = Date.now();
    await g.goto(`https://www.google.com/travel/flights?tfs=${encodeURIComponent(tfs)}${extra}`, { waitUntil: 'domcontentloaded' });
    await g.waitForFunction(() => document.querySelectorAll('li div[aria-label]').length > 2, null, { timeout: 40000 }).catch(() => {});
    const labels = await g.evaluate(() => [...document.querySelectorAll('li div[aria-label]')].map(e => e.getAttribute('aria-label')).filter(a => /\d{3}/.test(a)).slice(0, 3));
    const text = (await g.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ');
    console.log(`#### google_${lang}_${name} ms=${Date.now() - t0} labels=${JSON.stringify(labels)} text=${text.slice(0, 500)}`);
    await g.close();
  }
  await ctx.close();
}
await browser.close();

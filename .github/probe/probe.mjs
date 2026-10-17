// Temporary research probe run on a GitHub runner (open egress).
import { chromium } from 'playwright';

const ARTICLES = [
  'https://huitinchou.tw/2025-reverse-ticket-vs-4-segment-ticket/',
  'https://huitinchou.tw/reverse-ticketing-guide-%E6%A9%9F%E7%A5%A8%E5%80%92%E8%B2%B7%E6%B3%95/',
  'https://huitinchou.tw/2025-fourth-leg-guide-taiwan-airlines-2025/',
];
const SEG = [['HKG','TPE','2027-02-05'],['TPE','NRT','2027-02-05'],['NRT','TPE','2027-02-17'],['TPE','HKG','2027-12-23']];
const lc = s => s.toLowerCase();
const LINKS = {
  'trip_mt_lower': `https://www.trip.com/flights/showfarefirst?dcity=${SEG.map(s=>lc(s[0])).join(',')}&acity=${SEG.map(s=>lc(s[1])).join(',')}&ddate=${SEG.map(s=>s[2]).join(',')}&triptype=mt&class=y&quantity=1&locale=zh-TW&curr=TWD`,
  'trip_MT_upper': `https://www.trip.com/flights/showfarefirst?dcity=${SEG.map(s=>s[0]).join(',')}&acity=${SEG.map(s=>s[1]).join(',')}&ddate=${SEG.map(s=>s[2]).join(',')}&triptype=MT&class=Y&quantity=1&locale=zh-TW&curr=TWD`,
  'trip_rt_reference': 'https://www.trip.com/flights/showfarefirst?dcity=tpe&acity=nrt&ddate=2027-02-05&rdate=2027-02-15&triptype=rt&class=y&quantity=1&locale=zh-TW&curr=TWD',
  'skyscanner_d': `https://www.skyscanner.com.tw/transport/d/${SEG.map(([o,d,day])=>`${lc(o)}/${day}/${lc(d)}`).join('/')}/?adultsv2=1&cabinclass=economy`,
  'google_tfs': 'https://www.google.com/travel/flights?tfs=GhoSCjIwMjctMDItMDdqBRIDSEtHcgUSA1RQRRoaEgoyMDI3LTAyLTA3agUSA1RQRXIFEgNOUlQaGhIKMjAyNy0wMi0xNWoFEgNOUlRyBRIDVFBFGhoSCjIwMjctMTItMjJqBRIDVFBFcgUSA0hLR0IBAUgBmAED&hl=zh-TW&curr=TWD',
};

const browser = await chromium.launch();
const ctx = await browser.newContext({ locale: 'zh-TW', userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36', viewport: { width: 1366, height: 1000 } });

for (const url of ARTICLES) {
  const page = await ctx.newPage();
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    const text = await page.evaluate(() => (document.querySelector('article, .entry-content, main') || document.body).innerText);
    console.log(`\n######## ARTICLE ${url}\n${text.replace(/\n{2,}/g, '\n').slice(0, 14000)}\n######## END ARTICLE`);
  } catch (e) { console.log(`ARTICLE FAIL ${url} ${e}`); }
  await page.close();
}

for (const [name, url] of Object.entries(LINKS)) {
  const page = await ctx.newPage();
  try {
    const resp = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(12000);
    const text = (await page.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ');
    const inputs = await page.evaluate(() => [...document.querySelectorAll('input')].map(i => i.value).filter(Boolean).slice(0, 30));
    console.log(`\n######## LINK ${name}\nstatus=${resp?.status()} final=${page.url()}\ntitle=${await page.title()}\ninputs=${JSON.stringify(inputs)}\ntext=${text.slice(0, 3000)}\n######## END LINK`);
    await page.screenshot({ path: `probe-${name}.png`, fullPage: false });
  } catch (e) { console.log(`LINK FAIL ${name} ${e}`); }
  await page.close();
}
await browser.close();

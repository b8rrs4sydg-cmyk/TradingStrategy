// Temporary research probe run on a GitHub runner (open egress).
import { chromium } from 'playwright';

const ARTICLES = [
  'https://huitinchou.tw/2025-reverse-ticket-vs-4-segment-ticket/',
  'https://huitinchou.tw/reverse-ticketing-guide-%E6%A9%9F%E7%A5%A8%E5%80%92%E8%B2%B7%E6%B3%95/',
];
const T = 'https://www.trip.com/flights/showfarefirst?';
const tail = '&class=y&quantity=1&locale=zh-TW&curr=TWD';
const LINKS = {
  rt_citycodes: `${T}dcity=tpe&acity=tyo&ddate=2027-02-05&rdate=2027-02-15&triptype=rt${tail}`,
  rt_city_plus_airport: `${T}dcity=tpe&acity=tyo&dairport=tpe&aairport=nrt&ddate=2027-02-05&rdate=2027-02-15&triptype=rt${tail}`,
  mt_citycodes_comma: `${T}dcity=hkg,tpe,tyo,tpe&acity=tpe,tyo,tpe,hkg&ddate=2027-02-05,2027-02-05,2027-02-17,2027-07-01&triptype=mt${tail}`,
  mt_indexed: `${T}triptype=mt&dcity0=hkg&acity0=tpe&ddate0=2027-02-05&dcity1=tpe&acity1=tyo&ddate1=2027-02-05&dcity2=tyo&acity2=tpe&ddate2=2027-02-17&dcity3=tpe&acity3=hkg&ddate3=2027-07-01${tail}`,
  mt_indexed_airports: `${T}triptype=mt&dcity=hkg,tpe,tyo,tpe&acity=tpe,tyo,tpe,hkg&ddate=2027-02-05,2027-02-05,2027-02-17,2027-07-01&dairport0=hkg&aairport0=tpe&dairport1=tpe&aairport1=nrt&dairport2=nrt&aairport2=tpe&dairport3=tpe&aairport3=hkg${tail}`,
};

const browser = await chromium.launch();
const ctx = await browser.newContext({ locale: 'zh-TW', userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36', viewport: { width: 1366, height: 1000 } });

for (const url of ARTICLES) {
  const page = await ctx.newPage();
  try {
    const resp = await page.goto(url, { waitUntil: 'networkidle', timeout: 90000 });
    await page.waitForTimeout(3000);
    const text = await page.evaluate(() => document.body.innerText);
    console.log(`\n######## ARTICLE ${url}\nstatus=${resp?.status()} title=${await page.title()} len=${text.length}\n${text.replace(/\n{2,}/g, '\n').slice(0, 16000)}\n######## END ARTICLE`);
  } catch (e) { console.log(`ARTICLE FAIL ${url} ${e}`); }
  await page.close();
}

async function summarize(page, name) {
  await page.waitForTimeout(12000);
  const text = (await page.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ');
  const inputs = await page.evaluate(() => [...document.querySelectorAll('input')].filter(i => i.type !== 'hidden').map(i => `${i.getAttribute('aria-label') || i.placeholder || i.name || ''}=${i.value}`).slice(0, 30));
  console.log(`\n######## ${name}\nfinal=${page.url()}\ntitle=${await page.title()}\ninputs=${JSON.stringify(inputs)}\ntext=${text.slice(0, 1400)}\n######## END`);
}

for (const [name, url] of Object.entries(LINKS)) {
  const page = await ctx.newPage();
  try { await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 }); await summarize(page, `LINK ${name}`); }
  catch (e) { console.log(`LINK FAIL ${name} ${e}`); }
  await page.close();
}

// Drive Trip.com's own multi-city form to capture the URL it generates.
const page = await ctx.newPage();
try {
  await page.goto('https://www.trip.com/flights/?locale=zh-TW&curr=TWD', { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForTimeout(6000);
  const tab = page.getByText(/^(Multi-city|多個城市|多城市)$/).first();
  await tab.click({ timeout: 15000 });
  await page.waitForTimeout(2000);
  const form = await page.evaluate(() => {
    const el = document.querySelector('[class*="search-box"], [class*="searchbox"], form') || document.body;
    return el.outerHTML.replace(/<svg[\s\S]*?<\/svg>/g, '').slice(0, 6000);
  });
  console.log(`\n######## MC FORM HTML\n${form}\n######## END`);
  const cityInputs = page.locator('input[placeholder*="From"], input[placeholder*="出發"], input[placeholder*="To"], input[placeholder*="目的"], input[aria-label*="From"], input[aria-label*="To"]');
  console.log('city inputs:', await cityInputs.count());
  const pairs = [['Hong Kong', 'Taipei'], ['Taipei', 'Tokyo']];
  for (let i = 0; i < pairs.length * 2 && i < await cityInputs.count(); i++) {
    const inp = cityInputs.nth(i);
    await inp.click();
    await inp.fill(pairs[Math.floor(i / 2)][i % 2]);
    await page.waitForTimeout(2500);
    await page.keyboard.press('ArrowDown').catch(() => {});
    await page.keyboard.press('Enter');
    await page.waitForTimeout(1000);
  }
  const popupPromise = ctx.waitForEvent('page', { timeout: 20000 }).catch(() => null);
  await page.getByRole('button', { name: /^(Search|搜尋|搜索)$/ }).first().click({ timeout: 10000 });
  const results = (await popupPromise) || page;
  await results.waitForLoadState('domcontentloaded').catch(() => {});
  await summarize(results, 'MC UI RESULT');
} catch (e) { console.log(`MC UI FAIL ${e}`); }
await browser.close();

// Temporary research probe run on a GitHub runner (open egress).
import { chromium } from 'playwright';
const ARTICLES = [
  'https://huitinchou.tw/2025-reverse-ticket-vs-4-segment-ticket/',
  'https://huitinchou.tw/reverse-ticketing-guide-%E6%A9%9F%E7%A5%A8%E5%80%92%E8%B2%B7%E6%B3%95/',
];
const T = 'https://www.trip.com/flights/showfarefirst?';
const tail = '&class=y&quantity=1&locale=zh-TW&curr=TWD';
const idx = segs => segs.map(([dc, ac, d, da, aa], i) => `dcity${i}=${dc}&acity${i}=${ac}&ddate${i}=${d}&dairport${i}=${da}&aairport${i}=${aa}`).join('&');
const LINKS = {
  mt_four: `${T}triptype=mt&${idx([['hkg','tpe','2027-02-05','hkg','tpe'],['tpe','tyo','2027-02-06','tpe','nrt'],['tyo','tpe','2027-02-17','nrt','tpe'],['tpe','hkg','2027-06-10','tpe','hkg']])}${tail}`,
  mt_two_openjaw: `${T}triptype=mt&${idx([['tpe','tyo','2027-02-05','tpe','nrt'],['osa','tpe','2027-06-10','kix','tpe']])}${tail}`,
  rt_reverse_ticket: `${T}dcity=tyo&acity=tpe&dairport=nrt&aairport=tpe&ddate=2027-02-15&rdate=2027-06-10&triptype=rt${tail}`,
  ow_airport: `${T}dcity=tpe&acity=hkg&dairport=tpe&aairport=hkg&ddate=2027-02-03&triptype=ow${tail}`,
};
const browser = await chromium.launch({ args: ['--disable-blink-features=AutomationControlled'] });
const ctx = await browser.newContext({ locale: 'zh-TW', userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36', viewport: { width: 1366, height: 1000 } });

async function readArticle(url) {
  for (const candidate of [url, `https://web.archive.org/web/2026/${url}`]) {
    const page = await ctx.newPage();
    try {
      await page.goto(candidate, { waitUntil: 'domcontentloaded', timeout: 60000 });
      for (let i = 0; i < 6; i++) {
        await page.waitForTimeout(5000);
        if (!/Just a moment|請稍候/.test(await page.title())) break;
      }
      const text = await page.evaluate(() => (document.querySelector('.entry-content, article') || document.body).innerText);
      if (text.length > 2000) {
        console.log(`\n######## ARTICLE ${candidate}\ntitle=${await page.title()} len=${text.length}\n${text.replace(/\n{2,}/g, '\n').slice(0, 15000)}\n######## END ARTICLE`);
        await page.close();
        return;
      }
      console.log(`ARTICLE SHORT ${candidate} title=${await page.title()} len=${text.length}`);
    } catch (e) { console.log(`ARTICLE FAIL ${candidate} ${e}`); }
    await page.close();
  }
}
for (const u of ARTICLES) await readArticle(u);

for (const [name, url] of Object.entries(LINKS)) {
  const page = await ctx.newPage();
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });
    await page.waitForTimeout(18000);
    const dateBits = await page.evaluate(() => [...document.querySelectorAll('[data-testid*="date" i], [class*="date" i]')]
      .map(e => `${e.getAttribute('data-testid') || e.className}::${(e.getAttribute('aria-label') || e.innerText || e.value || '').replace(/\s+/g, ' ')}`)
      .filter(s => /\d/.test(s)).slice(0, 25));
    const text = (await page.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ');
    const at = Math.max(0, text.indexOf('Multi-city'));
    console.log(`\n######## ${name}\nfinal=${page.url()}\ntitle=${await page.title()}\ndateBits=${JSON.stringify(dateBits)}\ntext=${text.slice(at, at + 900)}\n######## END`);
  } catch (e) { console.log(`FAIL ${name} ${e}`); }
  await page.close();
}
await browser.close();

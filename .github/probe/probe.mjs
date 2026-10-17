// Temporary research probe (deleted after use): Google Flights multi-city prices.
import { chromium } from 'playwright';
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36';
const browser = await chromium.launch({ args: ['--disable-blink-features=AutomationControlled'] });
const ctx = await browser.newContext({ locale: 'en-US', userAgent: UA });
const G = {
  mc4: 'GhoSCjIwMjctMDItMDVqBRIDSEtHcgUSA1RQRRoaEgoyMDI3LTAyLTA1agUSA1RQRXIFEgNOUlQaGhIKMjAyNy0wMi0xN2oFEgNOUlRyBRIDVFBFGhoSCjIwMjctMDQtMDNqBRIDVFBFcgUSA0hLR0IBAUgBmAED',
  mc2: 'GhoSCjIwMjctMDItMDVqBRIDVFBFcgUSA0tJWBoaEgoyMDI3LTAyLTE1agUSA05SVHIFEgNUUEVCAQFIAZgBAw==',
};
async function run(name, tfs, wait) {
  const g = await ctx.newPage();
  const t0 = Date.now();
  await g.goto(`https://www.google.com/travel/flights?tfs=${encodeURIComponent(tfs)}&hl=en&gl=TW&curr=TWD`, { waitUntil: 'domcontentloaded' });
  const ok = await g.waitForSelector("li div[aria-label*='New Taiwan dollars']", { timeout: wait }).then(() => true).catch(() => false);
  const labels = await g.evaluate(() => [...document.querySelectorAll("li div[aria-label*='New Taiwan dollars']")].map(e => e.getAttribute('aria-label')).slice(0, 3));
  const text = (await g.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ');
  console.log(`#### ${name} ok=${ok} ms=${Date.now() - t0} labels=${JSON.stringify(labels)} text=${text.slice(300, 900)}`);
  await g.close();
}
await run('mc4', G.mc4, 45000);
if (G.mc2) await run('mc2', G.mc2, 45000);
// does scrolling / waiting for network idle help?
const g = await ctx.newPage();
await g.goto(`https://www.google.com/travel/flights?tfs=${encodeURIComponent(G.mc4)}&hl=en&gl=TW&curr=TWD`, { waitUntil: 'networkidle', timeout: 60000 }).catch(() => {});
await g.waitForTimeout(8000);
console.log('#### mc4_idle', (await g.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ').slice(300, 900));
await browser.close();

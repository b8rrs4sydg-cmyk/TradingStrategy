"""End-to-end check of the published demo (GitHub Pages) in a real browser.

Scenarios (each prints a timeline; exit code 1 if anything is broken)::

  A  load + default search: build is current, database loaded, plans listed
  B  UI: sort, filter, select for compare, favourite, booking links
  C  live lookup: widen the search so fares are missing, watch the ntfy relay /
     fare daemon stream them back until the lookup is DONE
  D  四腿票 (three trips): LHR + NRT with HKG/ICN/BKK outstations, keep looking up what
     is missing until the search is complete, then a 四腿票 plan must be listed
     with its three trips, three ticket roles and booking links

    python -m scripts.e2e_pages https://b8rrs4sydg-cmyk.github.io/TradingStrategy/ [budget_seconds]
"""

from __future__ import annotations

import asyncio
import sys
import time
from itertools import pairwise

from playwright.async_api import Page, async_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://b8rrs4sydg-cmyk.github.io/TradingStrategy/"
BUDGET_S = float(sys.argv[2]) if len(sys.argv) > 2 else 1500
problems: list[str] = []


def log(*a) -> None:
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


def check(ok: bool, msg: str) -> None:
    log(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        problems.append(msg)


STATE = """() => ({
  status: live.doc && live.doc.status, found: live.doc && live.doc.found, done: live.doc && live.doc.done,
  total: live.doc && live.doc.total, mode: live.mode, transport: live.transport, error: live.error, rid: live.rid,
  plans: state.result ? state.result.plans.length : -1,
  four: state.result ? state.result.plans.filter(p => p.strategy === 'back_to_back_4leg').length : -1,
  missing: fareStats.missingKeys.size,
})"""


async def set_checked(page: Page, picker: str, codes: list[str] | None) -> None:
    await page.evaluate(
        """([picker, codes]) => {
          document.querySelectorAll('#' + picker + ' input').forEach(i => {
            i.checked = codes === null ? true : codes.includes(i.value);
            i.dispatchEvent(new Event('change', {bubbles: true}));
          });
        }""",
        [picker, codes],
    )


async def submit(page: Page) -> None:
    await page.evaluate("document.getElementById('search-form').requestSubmit()")
    await page.wait_for_timeout(1500)


async def wait_lookup(page: Page, cap_s: float, tag: str) -> dict:
    """Wait until the running lookup is done (or failed); returns the last state."""

    t0, last, st = time.time(), "", {}
    while time.time() - t0 < cap_s:
        await page.wait_for_timeout(3000)
        st = await page.evaluate(STATE)
        line = f"{st['status']} {st['done']}/{st['total']} found={st['found']} plans={st['plans']} four={st['four']} via={st['transport']}"
        if line != last:
            log(f"[{tag}]", line)
            last = line
        if st["error"] or st["status"] in ("done", "error") or st["rid"] is None:
            break
    return st


async def main() -> int:
    t_start = time.time()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))

        # ---- A: load ---------------------------------------------------------
        resp = await page.goto(URL, wait_until="load")
        check(bool(resp and resp.status == 200), f"HTTP {resp.status if resp else None}")
        await page.wait_for_timeout(2500)
        info = await page.evaluate(
            """() => ({fares: Object.keys(FARES.fares).length, slots: slots.length,
                      triple: typeof planFourLegTriple === 'function', ntfy: typeof ntfyLookup === 'function',
                      plans: state.result ? state.result.plans.length : -1,
                      cards: document.querySelectorAll('article.plan').length})"""
        )
        log("loaded:", info)
        check(info["triple"] and info["ntfy"], "page is the latest build")
        check(info["fares"] > 500, f"fare database loaded ({info['fares']})")
        check(info["slots"] == 3, f"three default time slots ({info['slots']})")
        check(info["plans"] > 0 and info["cards"] > 0, f"default search lists plans ({info['plans']}/{info['cards']} cards)")

        # ---- B: UI -----------------------------------------------------------
        await page.select_option("#r-sort", "price")
        await page.wait_for_timeout(500)
        prices = await page.evaluate(
            "[...document.querySelectorAll('article.plan')].slice(0, 6).map(a => a.innerText.match(/TWD\\s*([\\d,]+)/)?.[1]).map(s => s && Number(s.replace(/,/g, '')))"
        )
        log("cheapest-first prices:", prices)
        check(all(a <= b for a, b in pairwise(prices) if a and b), "sort by price is ascending")
        await page.select_option("#r-sort", "score")
        opts = await page.evaluate("[...document.querySelectorAll('#r-filter option')].map(o => o.value)")
        for v in [o for o in opts if o != "all"][:2]:
            await page.select_option("#r-filter", v)
            await page.wait_for_timeout(300)
            n = await page.evaluate("document.querySelectorAll('article.plan').length")
            check(n >= 0, f"filter {v}: {n} plans")
        await page.select_option("#r-filter", "all")
        boxes = page.locator("article.plan .sel-col input[type=checkbox]")
        if await boxes.count() >= 2:
            await boxes.nth(0).check()
            await boxes.nth(1).check()
            pill = await page.inner_text("#r-sel-pill")
            check("2" in pill, f"compare selection pill: {pill!r}")
            await boxes.nth(0).uncheck()
            await boxes.nth(1).uncheck()
        await page.locator("article.plan .fav-btn").first.click()
        links = await page.evaluate(
            "[...document.querySelectorAll('article.plan a[href]')].map(a => a.href).filter(h => h.startsWith('http'))"
        )
        check(len(links) > 0 and any("google.com/travel/flights" in h for h in links), f"booking links present ({len(links)})")

        # ---- C: live lookup, widened search ------------------------------------
        await set_checked(page, "pick-dest", None)
        await submit(page)
        st = await wait_lookup(page, min(900, BUDGET_S / 2), "C")
        check(st["status"] == "done", f"live lookup completes (status={st['status']}, found={st['found']})")
        check((st["found"] or 0) > 0, "fares streamed back from the crawler")
        check(st["transport"] == "http", f"page reached the crawler through its direct tunnel (transport={st['transport']})")
        check(not st["error"], f"no lookup error ({st['error']})")

        # ---- D: 四腿票, narrowed so the lookup can finish --------------------------
        await page.goto(URL, wait_until="load")   # fresh page: scenario C's campaign must not run on
        await page.wait_for_timeout(2500)
        await set_checked(page, "pick-dest", ["LHR", "NRT"])
        await set_checked(page, "pick-outer", ["HKG", "ICN", "BKK"])
        rounds = 0
        d_deadline = time.time() + 900
        while time.time() < min(d_deadline, t_start + BUDGET_S) and rounds < 15:
            rounds += 1
            await submit(page)
            st = await page.evaluate(STATE)
            if st["four"] >= 1 or (st["rid"] is None and not st["error"]):
                break  # a 四腿票 plan is already listed, or nothing is left to look up
            st = await wait_lookup(page, 600, f"D{rounds}")
            if st["error"]:
                break
        st = await page.evaluate(STATE)
        log("D final:", st)
        check(not st["error"], f"no lookup error ({st['error']})")
        check(st["four"] >= 1, f"a 四腿票 plan is listed ({st['four']})")
        if st["four"] >= 1:
            await page.select_option("#r-filter", "back_to_back_4leg")
            card = await page.evaluate(
                """() => { const a = document.querySelector('article.plan.four-leg'); return a ? a.innerText : ''; }"""
            )
            log("四腿票 card:", card.replace("\n", " | ")[:700])
            check("旅程 1" in card and "旅程 2" in card and "旅程 3" in card, "card shows the three trips")
            check("單買初段" in card and "外站四腿票" in card and "單買最後一段" in card, "card shows the three ticket roles")
            hrefs = await page.evaluate(
                "[...document.querySelectorAll('article.plan.four-leg a[href]')].map(a => a.href)"
            )
            check(any("multdcity3" in h or "tfs=" in h for h in hrefs), "multi-city booking links on the 四腿票")

        real = [e for e in errors if "favicon" not in e and "net::ERR" not in e]
        check(not real, f"no page errors {real[:3]}")
        await browser.close()
    if problems:
        log("FAILED:\n - " + "\n - ".join(problems))
        return 1
    log("OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
# rerun 16:55
# rerun 17:04
# rerun 17:13
# rerun 17:35
# rerun 17:47
# rerun 18:07

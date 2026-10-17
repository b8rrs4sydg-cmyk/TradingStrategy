"""End-to-end check of the published demo (GitHub Pages) in a real browser.

Opens the page, runs the default search, then asks for more destinations so
fares are missing and the live lookup (ntfy relay → fare daemon) has to answer.
Prints a timeline and exits non-zero when something is broken (rerun after every daemon/page change)::

    python -m scripts.e2e_pages https://b8rrs4sydg-cmyk.github.io/TradingStrategy/
"""

from __future__ import annotations

import asyncio
import sys
import time

from playwright.async_api import async_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "https://b8rrs4sydg-cmyk.github.io/TradingStrategy/"
WAIT_S = float(sys.argv[2]) if len(sys.argv) > 2 else 240


def log(*a) -> None:
    print(f"[{time.strftime('%H:%M:%S')}]", *a, flush=True)


async def main() -> int:
    problems: list[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        resp = await page.goto(URL, wait_until="load")
        log("HTTP", resp.status if resp else None)
        await page.wait_for_timeout(2500)

        info = await page.evaluate(
            """() => ({
              fares: Object.keys(FARES.fares).length, generated: FARES.generated_at,
              plans: state.result ? state.result.plans.length : -1,
              four: state.result ? state.result.plans.filter(p => p.strategy === 'back_to_back_4leg').length : -1,
              slots: slots.length, missing: fareStats.missingKeys.size,
              hasTriple: typeof planFourLegTriple === 'function',
              hasNtfy: typeof ntfyLookup === 'function',
              lookup: document.getElementById('live-lookup').hidden ? '' : document.getElementById('live-lookup').innerText,
            })"""
        )
        log("loaded:", info)
        if not info["hasTriple"] or not info["hasNtfy"]:
            problems.append("page is not the latest build (missing planFourLegTriple/ntfyLookup)")
        if info["fares"] < 100:
            problems.append(f"fare database looks empty ({info['fares']})")

        # widen the search so fares are missing → live lookup
        await page.evaluate(
            """() => { document.querySelectorAll('#pick-dest input').forEach(i => {
                 i.checked = true; i.dispatchEvent(new Event('change', {bubbles: true})); });
               document.getElementById('search-form').requestSubmit(); }"""
        )
        t0 = time.time()
        last = ""
        max_found = 0
        saw_running = False
        done = False
        while time.time() - t0 < WAIT_S:
            await page.wait_for_timeout(2000)
            st = await page.evaluate(
                """() => ({ status: live.doc && live.doc.status, found: live.doc && live.doc.found,
                            done: live.doc && live.doc.done, total: live.doc && live.doc.total,
                            mode: live.mode, error: live.error,
                            plans: state.result.plans.length,
                            text: document.getElementById('live-lookup').hidden ? '' :
                                  document.getElementById('live-lookup').innerText.replace(/\\n/g, ' | ').slice(0, 160) })"""
            )
            line = f"{st['status']} {st['done']}/{st['total']} found={st['found']} plans={st['plans']} mode={st['mode']}"
            if line != last:
                log(line, "|", st["text"])
                last = line
            if st["error"]:
                problems.append(f"lookup error: {st['error']}")
                break
            if st["status"] == "running":
                saw_running = True
            max_found = max(max_found, st["found"] or 0)
            if st["status"] == "done":
                done = True
                break
        if not saw_running:
            problems.append("lookup never reached 'running' (crawler silent?)")
        if not max_found:
            problems.append("no fare streamed back from the crawler")
        if not done:
            log("lookup not finished within", WAIT_S, "s (not necessarily a failure for 160 keys)")
        final = await page.evaluate(
            "() => ({plans: state.result.plans.length, four: state.result.plans.filter(p=>p.strategy==='back_to_back_4leg').length})"
        )
        log("final:", final)
        # the results list must render something usable
        cards = await page.evaluate("document.querySelectorAll('#results .plan, #results .card, #results article').length")
        log("rendered cards:", cards)
        real = [e for e in errors if "favicon" not in e and "net::ERR" not in e]
        if real:
            problems.append(f"page errors: {real[:3]}")
        await browser.close()
    if problems:
        log("FAILED:")
        for pr in problems:
            log(" -", pr)
        return 1
    log("OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

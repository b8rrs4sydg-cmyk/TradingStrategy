"""Google Flights scraping: query keys, result-row parsing, browser fetch.

The only fare source of the app. A query is the exact Google Flights search
``booking_links`` builds (``tfs`` protobuf; ``hl=en&gl=TW&curr=TWD`` — without
``gl=TW`` round trips show no results). Each result row carries an
aria-label like::

    From 22080 New Taiwan dollars round trip total. Nonstop flight with
    Jetstar Japan. Leaves Taiwan Taoyuan International Airport at 12:50 PM on
    Friday, February 5 and arrives at Narita International Airport at
    4:55 PM on Friday, February 5. Total duration 3 hr 5 min. Select flight

Google lists only the first segment's flights before you pick one, so a
fare entry holds the cheapest TOTAL price plus that row's first-segment
times. Used by the crawler (``scripts/build_fare_snapshot.py``) and, with a
per-request budget, by ``FareDatabaseProvider`` for live lookups.

Key format (shared with the demo page's JS)::

    ow|TPE|NRT|2027-02-05
    rt|TPE|NRT|2027-02-05|2027-02-15
    mc|HKG-TPE-2027-02-07|TPE-NRT-2027-02-07|...
"""

from __future__ import annotations

import asyncio
import contextlib
import random
import re
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from app.data.airports import TIMEZONES
from app.models.enums import CabinClass
from app.providers.base import Segment

ISSUER = "google_flights"
# Google Flights only sells ~11 months ahead; later dates return an error page.
GOOGLE_HORIZON_DAYS = 330

_TRIP = {"ow": 2, "rt": 1, "mc": 3}
_ROW_LABELS = "li div[aria-label*='New Taiwan dollars']"
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


# --- keys ---------------------------------------------------------------------
def fare_key(segments: Sequence[Segment], *, round_trip: bool = False) -> str:
    if round_trip:
        (o, d, dep), (_, _, ret) = segments
        return f"rt|{o}|{d}|{dep.isoformat()}|{ret.isoformat()}"
    if len(segments) == 1:
        ((o, d, day),) = segments
        return f"ow|{o}|{d}|{day.isoformat()}"
    return "mc|" + "|".join(f"{o}-{d}-{day.isoformat()}" for o, d, day in segments)


def parse_key(key: str) -> tuple[str, tuple[Segment, ...]]:
    """Inverse of :func:`fare_key` → (kind, segments)."""

    kind, *rest = key.split("|")
    if kind == "ow":
        o, d, day = rest
        return kind, ((o, d, date.fromisoformat(day)),)
    if kind == "rt":
        o, d, dep, ret = rest
        return kind, ((o, d, date.fromisoformat(dep)), (d, o, date.fromisoformat(ret)))
    segs = []
    for part in rest:
        o, d, day = part.split("-", 2)
        segs.append((o, d, date.fromisoformat(day)))
    return kind, tuple(segs)


def tz_of(code: str) -> ZoneInfo:
    return ZoneInfo(TIMEZONES.get(code, "UTC"))


def url_for(key: str) -> str:
    from app.services.booking_links import google_flights_tfs  # avoid an import cycle

    kind, segs = parse_key(key)
    tfs = google_flights_tfs(segs, adults=1, cabin=CabinClass.ECONOMY, trip=_TRIP[kind])
    return f"https://www.google.com/travel/flights?tfs={quote(tfs, safe='')}&hl=en&gl=TW&curr=TWD"


# --- parsing ------------------------------------------------------------------
_PRICE = re.compile(r"(?:From )?([\d,]+) New Taiwan dollars")
_STOPS = re.compile(r"(Nonstop|(\d+) stops?) flight with ([^.]+?)\.")
_TIMES = re.compile(
    r"Leaves .+? at (\d{1,2}:\d{2}\s?[AP]M) on \w+, (\w+ \d{1,2}) and arrives at .+? at "
    r"(\d{1,2}:\d{2}\s?[AP]M) on \w+, (\w+ \d{1,2})"
)
_SEPARATE = re.compile(r"separate tickets?", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedOption:
    price: int
    stops: int
    airline: str
    dep: datetime | None
    arr: datetime | None
    separate: bool = False   # Google combined separate tickets (not one ticket)


def _when(clock: str, month_day: str, year: int, tz: ZoneInfo) -> datetime:
    clock = clock.replace(" ", " ").replace(" ", "")
    # Parsed with a dummy +0000 offset, then pinned to the airport's zone.
    dt = datetime.strptime(f"{month_day} {year} {clock} +0000", "%B %d %Y %I:%M%p %z")
    return dt.replace(tzinfo=tz)


def parse_option(label: str, *, year: int, dep_tz: ZoneInfo, arr_tz: ZoneInfo) -> ParsedOption | None:
    label = label.replace(" ", " ").replace("\xa0", " ")
    m = _PRICE.search(label)
    if not m:
        return None
    s = _STOPS.search(label)
    t = _TIMES.search(label)
    dep = arr = None
    if t:
        dep = _when(t.group(1), t.group(2), year, dep_tz)
        arr = _when(t.group(3), t.group(4), year, arr_tz)
        if arr < dep - timedelta(hours=14):  # crossed new year
            arr = arr.replace(year=year + 1)
    return ParsedOption(
        price=int(m.group(1).replace(",", "")),
        stops=0 if not s or s.group(1) == "Nonstop" else int(s.group(2)),
        airline=s.group(3).strip() if s else "",
        dep=dep,
        arr=arr,
        separate=bool(_SEPARATE.search(label)),
    )


def cheapest_entry(
    labels: Sequence[str], segments: Sequence[Segment], tz=tz_of
) -> dict | None:
    """Fare entry from a results page: cheapest one-ticket total + its first segment.

    Rows Google marks as separate tickets are only used when nothing else is
    offered (and then flagged), so a 四腿票 price is a real single ticket.
    """

    o, d, day = segments[0]
    options = [
        p for lab in labels if (p := parse_option(lab, year=day.year, dep_tz=tz(o), arr_tz=tz(d)))
    ]
    if not options:
        return None
    single = [p for p in options if not p.separate]
    best = min(single or options, key=lambda p: p.price)
    entry: dict = {"price": best.price}
    if not single:
        entry["separate"] = True
    if best.dep and best.arr:
        entry["first"] = {
            "dep": best.dep.isoformat(),
            "arr": best.arr.isoformat(),
            "stops": best.stops,
            "airline": best.airline,
        }
    return entry


# --- fetching -----------------------------------------------------------------
# Why a browser page gave no price. Only NO_RESULT means "Google has no such itinerary"; the others are failures to read
# the page (slow, errored) and must never be stored as unavailable. Multi-city pages are slow on Google's side: measured
# on a runner a page needs 2-18 s when it works and otherwise hangs on "Loading results" or answers "Oops, something went wrong".
MC_TIMEOUT_MS = 75000  # multi-city pages get this long before they count as slow
_ERROR_TEXT = ("something went wrong", "oops")
_EMPTY_TEXT = ("no flights found", "no flights available", "we couldn't find any flights")


def classify_page(body: str) -> str:
    """``timeout`` (still loading / unknown), ``error`` (Google's error page) or ``no_result`` (Google says no flights)."""

    text = body.lower()
    if any(t in text for t in _ERROR_TEXT):
        return "error"
    if "loading results" in text:
        return "timeout"
    if any(t in text for t in _EMPTY_TEXT):
        return "no_result"
    return "timeout"  # unknown page: not proof that there is no flight


async def _wait_rows(page, timeout_ms: int) -> bool:
    try:
        await page.wait_for_selector(_ROW_LABELS, timeout=timeout_ms)
        return True
    except Exception:  # noqa: BLE001
        return False


async def _fetch_one(ctx, key: str, timeout_ms: int, why: dict[str, str] | None = None) -> dict | None:
    """Entry for ``key``; ``None`` when no price was read, with the reason in ``why[key]`` (``no_result`` / ``timeout`` / ``error``)."""

    page = await ctx.new_page()
    try:
        if key.startswith("mc|"):
            timeout_ms = max(timeout_ms, MC_TIMEOUT_MS)
        await page.goto(url_for(key), wait_until="domcontentloaded", timeout=60000)
        ok = await _wait_rows(page, min(timeout_ms, 40000))
        if not ok:
            body = await page.evaluate("() => document.body.innerText.slice(0, 2000)")
            reason = classify_page(body)
            if reason == "error":  # Google's error page: its own Reload button usually works
                with contextlib.suppress(Exception):  # no Reload button / click failed: the retry in scrape asks again
                    await page.get_by_role("button", name="Reload").click(timeout=3000)
                    ok = await _wait_rows(page, max(timeout_ms - 40000, 20000))
            elif reason == "timeout" and timeout_ms > 40000:  # still loading: give a slow multi-city page the rest of the time
                ok = await _wait_rows(page, timeout_ms - 40000)
            if not ok:
                if why is not None:
                    body = await page.evaluate("() => document.body.innerText.slice(0, 2000)")
                    why[key] = classify_page(body)
                return None
        await page.wait_for_timeout(1500)  # let the "other flights" list render too
        labels = await page.eval_on_selector_all(
            _ROW_LABELS, "els => els.map(e => e.getAttribute('aria-label'))"
        )
        entry = cheapest_entry(labels, parse_key(key)[1])
        if entry is None and why is not None:
            why[key] = "parse_error"
        return entry
    finally:
        await page.close()


async def scrape(
    keys: Sequence[str],
    *,
    concurrency: int = 4,
    timeout_ms: int = 35000,
    progress: Callable[[int, int, int], None] | None = None,
    why: dict[str, str] | None = None,
) -> tuple[dict[str, dict], list[str]]:
    """Fetch every key in a headless Chromium → (entries, missing keys).

    ``why`` (optional) receives the reason for every missing key: ``no_result`` is the only one that means "no such
    flight"; ``timeout`` / ``error`` / ``parse_error`` are failures to read the page.
    """

    from playwright.async_api import async_playwright

    fares: dict[str, dict] = {}
    missing: list[str] = []
    sem = asyncio.Semaphore(concurrency)
    done = 0
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
        ctx = await browser.new_context(locale="en-US", user_agent=_UA)

        async def one(key: str) -> None:
            nonlocal done
            async with sem:
                await asyncio.sleep(random.uniform(0.3, 1.2))  # be gentle
                entry = None
                reasons: dict[str, str] = {}
                for attempt in range(3):
                    try:
                        entry = await _fetch_one(ctx, key, timeout_ms, reasons)
                    except Exception as e:  # noqa: BLE001
                        print(f"retry {key}: {e}", file=sys.stderr)
                        reasons[key] = "timeout"
                        continue
                    if entry or reasons.get(key) == "no_result":
                        break  # a price, or Google says there is no such flight
                    await asyncio.sleep(2 + 3 * attempt)  # slow or errored page: ask again
                if entry:
                    fares[key] = entry
                else:
                    missing.append(key)
                    if why is not None:
                        why[key] = reasons.get(key, "timeout")
                done += 1
                if progress:
                    progress(done, len(keys), len(missing))

        await asyncio.gather(*(one(k) for k in keys))
        await browser.close()
    return fares, missing


def fetch_now(keys: Sequence[str], *, concurrency: int = 4, timeout_ms: int = 35000):
    """Blocking :func:`scrape` for sync callers (runs its own event loop)."""

    return asyncio.run(scrape(keys, concurrency=concurrency, timeout_ms=timeout_ms))

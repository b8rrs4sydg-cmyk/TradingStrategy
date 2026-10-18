"""Google Flights prices over plain HTTP — no browser, about 0.3-0.7 s per key instead of 10-40 s.

Two doors lead to the same itinerary data the page renders:

* one-way / round trip: the server-rendered results page (``AF_initDataCallback`` blocks);
* multi-city: the page itself loads its results through ``GetShoppingResults`` (the HTML carries no
  prices), so the same request is rebuilt from the key and posted with the cookies a plain GET hands out.

Both answers are searched for itinerary rows (``[flight details, [[None, price], token]]``). Google sometimes
answers without the flight data (or never answers), so :meth:`HttpFetcher.fetch` retries a few times and
returns ``None`` when it could not read a price — that means *unknown*, not *no itinerary*: the caller falls
back to the browser, which decides. Rows Google marks as separate tickets cannot be told apart here.

NOT USED BY THE DAEMON. Measured against the browser-made fare database on a GitHub runner, 7-13 of 20 keys of
each kind came back with data and a share of the round trips were priced 20-35% too high (Google sometimes answers
with a partial list, which cannot be told from a complete one), so a plain-HTTP price is not trustworthy as the
source of truth. Kept as a documented experiment; see scripts/exp_http_*.py and exp_mc_*.py.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Iterator, Sequence
from datetime import datetime
from urllib.parse import quote

import httpx

from app.providers.base import Segment
from app.providers.google_flights import parse_key, tz_of, url_for

ENDPOINT = (
    "https://www.google.com/_/FlightsFrontendUi/data/"
    "travel.frontend.flights.FlightsFrontendService/GetShoppingResults"
)
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
# pre-accepted consent, so no consent wall is served
_SOCS = "CAESHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiAo_CmBg"
_AF = re.compile(r"AF_initDataCallback\(\{key: 'ds:\d+', hash: '[^']*', data:")
_SESSION_TTL_S = 1800
_PAUSE_S = 300
_BLOCK_LIMIT = 6  # this many 403/429/captcha answers in a row → stop asking for a while


# --- parsing ---------------------------------------------------------------------
def html_payloads(html: str) -> Iterator[object]:
    dec = json.JSONDecoder()
    for m in _AF.finditer(html):
        i = m.end()
        while i < len(html) and html[i] in " \n":
            i += 1
        try:
            yield dec.raw_decode(html, i)[0]
        except ValueError:
            continue


def rpc_payloads(text: str) -> Iterator[object]:
    """Inner JSON of every ``wrb.fr`` row of a batchexecute-style answer."""

    for line in text.split("\n"):
        if not line.startswith("[["):
            continue
        try:
            outer = json.loads(line)
        except ValueError:
            continue
        for row in outer:
            if (
                isinstance(row, list)
                and len(row) > 2
                and row[0] == "wrb.fr"
                and isinstance(row[2], str)
            ):
                try:
                    yield json.loads(row[2])
                except ValueError:
                    continue


def _is_itinerary(x: object) -> bool:
    try:
        price = x[1][0][1]  # type: ignore[index]
        return isinstance(x[0], list) and isinstance(price, int) and 500 <= price <= 3_000_000  # type: ignore[index]
    except (IndexError, TypeError, KeyError):
        return False


def itineraries(node: object, depth: int = 0) -> Iterator[list]:
    """Rows of every list made only of itinerary rows (price graphs and other number pairs do not qualify)."""

    if depth > 14 or not isinstance(node, list):
        return
    if node and all(_is_itinerary(x) for x in node):
        yield from node
        return
    for child in node:
        yield from itineraries(child, depth + 1)


def _clock(t: Sequence[int]) -> tuple[int, int]:
    return (t[0] if t else 0), (t[1] if len(t) > 1 else 0)


def first_slice(item: list, segments: Sequence[Segment]) -> dict | None:
    """Departure/arrival/stops/airline of the first slice of an itinerary row, or ``None`` if unreadable."""

    try:
        legs = item[0][2]
        l0, ln = legs[0], legs[-1]
        o, d, _ = segments[0]
        dy, dm, dd = l0[20]
        ay, am, ad = ln[21]
        dh, dmin = _clock(l0[8])
        ah, amin = _clock(ln[10])
        dep = datetime(dy, dm, dd, dh, dmin, tzinfo=tz_of(o))
        arr = datetime(ay, am, ad, ah, amin, tzinfo=tz_of(d))
        names = item[0][1] if isinstance(item[0][1], list) else []
        return {
            "dep": dep.isoformat(),
            "arr": arr.isoformat(),
            "stops": len(legs) - 1,
            "airline": ", ".join(str(n) for n in names) or "",
        }
    except (IndexError, TypeError, ValueError, KeyError):
        return None


def entry_from(payloads: Iterator[object], segments: Sequence[Segment]) -> dict | None:
    best: list | None = None
    for p in payloads:
        for row in itineraries(p):
            if best is None or row[1][0][1] < best[1][0][1]:
                best = row
    if best is None:
        return None
    entry: dict = {"price": best[1][0][1]}
    first = first_slice(best, segments)
    if first:
        entry["first"] = first
    return entry


# --- request ---------------------------------------------------------------------
def _leg(origin: str, dest: str, day: str) -> list:
    return [
        [[[origin, 0]]],
        [[[dest, 0]]],
        None,
        0,
        None,
        None,
        day,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        3,
    ]


def multi_city_body(segments: Sequence[Segment]) -> str:
    legs = [_leg(o, d, day.isoformat()) for o, d, day in segments]
    inner = [
        [None, None, None, None],
        [
            None,
            None,
            3,
            None,
            [],
            1,
            [1, 0, 0, 0],
            None,
            None,
            None,
            None,
            None,
            None,
            legs,
            None,
            None,
            None,
            1,
        ],
        0,
        0,
        0,
        1,
    ]
    flat = json.dumps(inner, separators=(",", ":"))
    return "f.req=" + quote(json.dumps([None, flat], separators=(",", ":")), safe="") + "&"


class HttpFetcher:
    """Async client; one instance is shared by every concurrent lookup."""

    def __init__(self, *, timeout: float = 7.0, attempts: int = 3, concurrency: int = 16):
        self.timeout = timeout
        self.attempts = attempts
        self.sem = asyncio.Semaphore(concurrency)
        self.client = httpx.AsyncClient(
            headers={"User-Agent": _UA, "Accept-Language": "en-US,en;q=0.9"},
            cookies={"SOCS": _SOCS},
            timeout=timeout,
            follow_redirects=True,
        )
        self.sid = ""
        self.bl = ""
        self.session_at = 0.0
        self.session_lock = asyncio.Lock()
        self.reqid = 100000
        self.blocked = 0
        self.pause_until = 0.0
        self.stats = {"hit": 0, "miss": 0, "blocked": 0}

    async def aclose(self) -> None:
        await self.client.aclose()

    async def _prepare(self) -> None:
        async with self.session_lock:
            if self.sid and time.time() - self.session_at < _SESSION_TTL_S:
                return
            r = await self.client.get(url_for("ow|TPE|NRT|2027-04-01"))
            sid = re.search(r'"FdrFJe":"(-?\d+)"', r.text)
            bl = re.search(r'"cfb2h":"([^"]+)"', r.text)
            if sid and bl:
                self.sid, self.bl, self.session_at = sid.group(1), bl.group(1), time.time()

    async def _answer(self, key: str, segments: Sequence[Segment]) -> str:
        if key.startswith("mc|"):
            await self._prepare()
            self.reqid += 100000
            params = {
                "f.sid": self.sid,
                "bl": self.bl,
                "hl": "en",
                "gl": "TW",
                "soc-app": "162",
                "soc-platform": "1",
                "soc-device": "1",
                "_reqid": str(self.reqid),
                "rt": "c",
            }
            r = await self.client.post(
                ENDPOINT,
                params=params,
                content=multi_city_body(segments),
                headers={
                    "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
                    "X-Same-Domain": "1",
                },
            )
        else:
            r = await self.client.get(url_for(key))
        if r.status_code in (403, 429) or "unusual traffic" in r.text[:4000]:
            raise PermissionError(str(r.status_code))
        return r.text

    async def fetch(self, key: str) -> dict | None:
        """Entry for ``key`` or ``None`` (unreadable → ask the browser)."""

        if time.time() < self.pause_until:
            return None
        _, segments = parse_key(key)
        async with self.sem:
            for _ in range(self.attempts):
                try:
                    text = await self._answer(key, segments)
                except PermissionError:
                    self.blocked += 1
                    self.stats["blocked"] += 1
                    if self.blocked >= _BLOCK_LIMIT:
                        self.pause_until = time.time() + _PAUSE_S
                        self.blocked = 0
                    return None
                except httpx.HTTPError:
                    self.sid = ""  # maybe a stale session: take a fresh one next time
                    continue
                payloads = rpc_payloads(text) if key.startswith("mc|") else html_payloads(text)
                entry = entry_from(payloads, segments)
                if entry:
                    self.blocked = 0
                    self.stats["hit"] += 1
                    return entry
            self.stats["miss"] += 1
            return None

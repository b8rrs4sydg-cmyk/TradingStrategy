"""Deep links to public flight-search sites for a ticket's route and dates.

Offers from the stub provider carry illustrative prices only, and the Amadeus
self-service API has no booking deep link — so every ticket gets search links
that open the same route / dates / pax / cabin on real sites where the live
fare can be checked and booked.

Formats were checked by opening the generated links in a real browser
(2026-10):

- Google Flights ``tfs`` (round trip / one-way / multi-city): route, dates
  and every segment load correctly.
- Trip.com (tw.trip.com, zh-TW): ``dcity``/``acity`` must be Trip.com
  *city* codes (tyo, osa, sel …) with ``dairport``/``aairport`` pinning
  the airport. Multi-city uses Trip.com's own format — the URL its search
  button produces: ``multdcity{i}``/``multacity{i}``/``dairport{i}``/
  ``aairport{i}``/``multddate{i}`` (0-based) + ``triptype=mt``.
- Skyscanner blocks automated browsers, so only its long-standing
  single-route ``/transport/flights/`` link is offered; no multi-city link.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING
from urllib.parse import quote, urlencode

from app.models.enums import CabinClass

if TYPE_CHECKING:  # strategies → schemas → booking_links would be circular
    from app.services.strategies.base import TicketOffer

_TRIP_CLASS = {
    CabinClass.ECONOMY: "y",
    CabinClass.PREMIUM_ECONOMY: "s",
    CabinClass.BUSINESS: "c",
    CabinClass.FIRST: "f",
}
_SKYSCANNER_CLASS = {
    CabinClass.ECONOMY: "economy",
    CabinClass.PREMIUM_ECONOMY: "premiumeconomy",
    CabinClass.BUSINESS: "business",
    CabinClass.FIRST: "first",
}
# Trip.com searches by metropolitan city code; anything absent maps to itself.
_TRIP_CITY = {
    "TSA": "tpe", "NRT": "tyo", "HND": "tyo", "KIX": "osa", "ITM": "osa",
    "CTS": "spk", "ICN": "sel", "GMP": "sel", "LHR": "lon", "LGW": "lon",
    "CDG": "par", "ORY": "par", "JFK": "nyc", "EWR": "nyc", "DMK": "bkk",
}
_TRIP_BASE = "https://tw.trip.com/flights/showfarefirst"


def _trip_city(code: str) -> str:
    return _TRIP_CITY.get(code, code.lower())


@dataclass(frozen=True, slots=True)
class BookingLink:
    source: str   # "trip_com" | "google_flights" | "skyscanner"
    label: str
    url: str


@dataclass(frozen=True, slots=True)
class _Route:
    origin: str
    destination: str
    depart: date
    return_: date | None


def _route_of(ticket: TicketOffer) -> _Route:
    legs = ticket.legs
    first, last = legs[0], legs[-1]
    if len(legs) >= 2 and last.destination == first.origin:
        # Round trip: the turnaround is the longest ground gap between legs
        # (connections are hours, the stay is days).
        turn = max(
            range(len(legs) - 1),
            key=lambda i: legs[i + 1].departure - legs[i].arrival,
        )
        return _Route(
            origin=first.origin,
            destination=legs[turn].destination,
            depart=first.departure.date(),
            return_=legs[turn + 1].departure.date(),
        )
    return _Route(first.origin, last.destination, first.departure.date(), None)


def _trip_com(r: _Route, adults: int, cabin: CabinClass) -> str:
    params = {
        "dcity": _trip_city(r.origin),
        "acity": _trip_city(r.destination),
        "dairport": r.origin.lower(),
        "aairport": r.destination.lower(),
        "ddate": r.depart.isoformat(),
        "triptype": "rt" if r.return_ else "ow",
        "class": _TRIP_CLASS[cabin],
        "quantity": adults,
        "locale": "zh-TW",
        "curr": "TWD",
    }
    if r.return_:
        params["rdate"] = r.return_.isoformat()
    return f"{_TRIP_BASE}?{urlencode(params)}"


def _google_flights(r: _Route, adults: int, cabin: CabinClass) -> str:
    segments = [(r.origin, r.destination, r.depart)]
    if r.return_:
        segments.append((r.destination, r.origin, r.return_))
    trip = _GOOGLE_TRIP_ROUND if r.return_ else _GOOGLE_TRIP_ONE_WAY
    return _google_url(google_flights_tfs(segments, adults=adults, cabin=cabin, trip=trip))


def _skyscanner(r: _Route, adults: int, cabin: CabinClass) -> str:
    path = f"{r.origin.lower()}/{r.destination.lower()}/{r.depart:%y%m%d}/"
    if r.return_:
        path += f"{r.return_:%y%m%d}/"
    params = urlencode({"adultsv2": adults, "cabinclass": _SKYSCANNER_CLASS[cabin]})
    return f"https://www.skyscanner.com.tw/transport/flights/{path}?{params}"


# --- multi-city -------------------------------------------------------------
# Tickets priced over several segments (倒買法 包覆票/反向票, 外站四腿票) must
# be searched as the same multi-city itinerary, not as a plain round trip.

_GOOGLE_SEAT = {
    CabinClass.ECONOMY: 1,
    CabinClass.PREMIUM_ECONOMY: 2,
    CabinClass.BUSINESS: 3,
    CabinClass.FIRST: 4,
}
_GOOGLE_TRIP_ROUND, _GOOGLE_TRIP_ONE_WAY, _GOOGLE_TRIP_MULTI_CITY = 1, 2, 3


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _pb_bytes(field: int, payload: bytes) -> bytes:
    return _varint(field << 3 | 2) + _varint(len(payload)) + payload


def _pb_varint(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def google_flights_tfs(
    segments: Sequence[tuple[str, str, date]],
    *,
    adults: int,
    cabin: CabinClass,
    trip: int = _GOOGLE_TRIP_MULTI_CITY,
) -> str:
    """Google Flights ``tfs`` query: base64 of the ``Info`` protobuf.

    Field numbers follow the reverse-engineered schema in the ``fast-flights``
    library: Info{data=3 (FlightData), passengers=8, seat=9, trip=19},
    FlightData{date=2, from_flight=13, to_flight=14}, Airport{airport=2}.
    """

    msg = b"".join(
        _pb_bytes(
            3,
            _pb_bytes(2, day.isoformat().encode())
            + _pb_bytes(13, _pb_bytes(2, o.encode()))
            + _pb_bytes(14, _pb_bytes(2, d.encode())),
        )
        for o, d, day in segments
    )
    msg += _pb_bytes(8, b"".join(_varint(1) for _ in range(adults)))  # ADULT, packed
    msg += _pb_varint(9, _GOOGLE_SEAT[cabin])
    msg += _pb_varint(19, trip)
    return base64.b64encode(msg).decode()


def _google_url(tfs: str) -> str:
    return f"https://www.google.com/travel/flights?tfs={quote(tfs, safe='')}&hl=zh-TW&curr=TWD"


def _mirrored(segments: Sequence[tuple[str, str, date]]) -> bool:
    return len(segments) == 2 and (segments[0][0], segments[0][1]) == (segments[1][1], segments[1][0])


def _multi_city_links(
    segments: Sequence[tuple[str, str, date]], adults: int, cabin: CabinClass
) -> list[BookingLink]:
    # Trip.com's own multi-city search URL (what its search button produces).
    params: dict[str, str | int] = {}
    for i, (o, d, day) in enumerate(segments):
        params |= {
            f"multdcity{i}": _trip_city(o),
            f"multacity{i}": _trip_city(d),
            f"dairport{i}": o.lower(),
            f"aairport{i}": d.lower(),
            f"multddate{i}": day.isoformat(),
        }
    params |= {
        "triptype": "mt",
        "class": _TRIP_CLASS[cabin],
        "quantity": adults,
        "searchboxarg": "t",
        "nonstoponly": "off",
        "locale": "zh-TW",
        "curr": "TWD",
    }
    # Google Flights answers a mirrored multi-city (A→B, B→A) with "No results
    # returned", so that pair is searched as its equivalent round trip there.
    if _mirrored(segments):
        tfs = google_flights_tfs(segments, adults=adults, cabin=cabin, trip=_GOOGLE_TRIP_ROUND)
        google = BookingLink("google_flights", "Google Flights 來回（Google 多段不支援同城往返）", _google_url(tfs))
    else:
        tfs = google_flights_tfs(segments, adults=adults, cabin=cabin)
        google = BookingLink("google_flights", "Google Flights 多段", _google_url(tfs))
    return [
        google,
        BookingLink(
            "trip_com",
            # Trip.com redirects a mirrored multi-city to its round-trip search
            # (mt2rt=true, both dates kept) whatever parameters are passed.
            "Trip.com 多段（同城往返會自動轉為來回，日期不變）" if _mirrored(segments) else "Trip.com 多段",
            f"{_TRIP_BASE}?{urlencode(params)}",
        ),
    ]


def booking_links(
    ticket: TicketOffer, *, adults: int = 1, cabin: CabinClass = CabinClass.ECONOMY
) -> list[BookingLink]:
    segs = ticket.searched_segments
    # Tickets a planner priced over several segments (倒買法 包覆票 / 反向票,
    # 四腿票) always open as multi-city — even a mirrored A→B, B→A pair, so the
    # two segments show on their own dates, months apart, as one ticket.
    if len(segs) >= 2:
        return _multi_city_links(segs, adults, cabin)
    r = _route_of(ticket)
    return [
        BookingLink("trip_com", "Trip.com", _trip_com(r, adults, cabin)),
        BookingLink("google_flights", "Google Flights", _google_flights(r, adults, cabin)),
        BookingLink("skyscanner", "Skyscanner", _skyscanner(r, adults, cabin)),
    ]

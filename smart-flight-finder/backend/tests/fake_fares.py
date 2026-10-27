"""Deterministic fake fare provider — TESTS ONLY, never a product price source.

The app's only fare source is the Google Flights fare database. Planner
and scoring tests still need prices that make every strategy pay off in a
predictable way, so this fake keeps the old demo fare model: +30% on
Taiwan-origin departures during 連假, outstation multi-city through TPE at
0.62x the summed one-ways, deterministic ±12% jitter.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import ClassVar

from app.data.airports import TW_AIRPORT_CODES
from app.data.taiwan_holidays_2027 import LEAVE_STRATEGIES
from app.models.enums import CabinClass
from app.providers.base import FlightOfferProvider, Segment
from app.services.strategies.base import FlightLeg, TicketOffer

TW_HOLIDAY_SURGE = 1.30
MULTI_CITY_FACTOR = 0.85
OUTSTATION_MULTI_CITY_FACTOR = 0.62
_HUB = "TPE"

# Departures from Taiwan on these days (each 連假 from the day before it
# starts to the day before it ends) are peak.
_TW_PEAK_DAYS: frozenset[date] = frozenset(
    s.window_start + timedelta(days=i)
    for s in LEAVE_STRATEGIES
    for i in range(-1, (s.window_end - s.window_start).days)
)


def market_factor(origin: str, day: date) -> float:
    return TW_HOLIDAY_SURGE if origin in TW_AIRPORT_CODES and day in _TW_PEAK_DAYS else 1.0


# (one-way TWD from TPE, block minutes, carrier) per destination
_SEED = {
    "NRT": (12800, 190, 'BR'),
    "HND": (14200, 185, 'CI'),
    "KIX": (11800, 180, 'JX'),
    "NGO": (11500, 175, 'CI'),
    "FUK": (10200, 150, 'CI'),
    "CTS": (13800, 245, 'BR'),
    "OKA": (8200, 90, 'CI'),
    "ICN": (9800, 160, 'KE'),
    "PUS": (9200, 135, 'BR'),
    "HKG": (5100, 90, 'CX'),
    "MFM": (5300, 95, 'NX'),
    "XMN": (4100, 90, 'MF'),
    "BKK": (10800, 230, 'TG'),
    "CNX": (11200, 245, 'BR'),
    "SGN": (8900, 215, 'BR'),
    "HAN": (9300, 200, 'CI'),
    "MNL": (7800, 140, 'PR'),
    "CEB": (8600, 170, 'JX'),
    "KUL": (10200, 285, 'MH'),
    "SIN": (11600, 280, 'SQ'),
    "LHR": (32000, 845, 'BR'),
    "CDG": (31500, 830, 'BR'),
    "AMS": (30500, 820, 'CI'),
    "VIE": (30000, 790, 'BR'),
    "LAX": (26500, 720, 'BR'),
    "SFO": (25800, 690, 'BR'),
    "JFK": (30800, 935, 'BR'),
    "YVR": (24500, 650, 'BR'),
    "SYD": (22800, 555, 'CI'),
    "BNE": (21900, 520, 'BR'),
}


class FakeFareProvider:
    """Reproducible pseudo-random offers for planner tests."""

    name: ClassVar[str] = "fake"

    # (base price in TWD, duration in minutes, carrier, direct?)
    _ROUTE_SEEDS: ClassVar[dict[tuple[str, str], tuple[int, int, str, bool]]] = {
        ("TPE", "NRT"): (12800, 190, "BR", True),
        ("NRT", "TPE"): (12500, 200, "BR", True),
        ("TPE", "HND"): (14200, 185, "CI", True),
        ("HND", "TPE"): (13900, 195, "CI", True),
        ("TPE", "KIX"): (11800, 180, "JX", True),
        ("KIX", "TPE"): (11600, 190, "JX", True),
        ("TPE", "ICN"): (9800, 160, "KE", True),
        ("ICN", "TPE"): (9700, 170, "KE", True),
        ("TPE", "BKK"): (10800, 230, "TG", True),
        ("BKK", "TPE"): (10900, 230, "TG", True),
        ("XMN", "TPE"): (4200, 85, "MF", True),
        ("TPE", "XMN"): (4100, 90, "MF", True),
        ("HKG", "TPE"): (5200, 90, "CX", True),
        ("TPE", "HKG"): (5100, 90, "CX", True),
    }

    def search(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: date,
        return_date: date | None = None,
        adults: int = 1,
    ) -> list[TicketOffer]:
        base_price, duration_min, carrier, direct = self._seed(origin, destination)
        market = market_factor(origin, departure_date)

        day_jitter = self._jitter((origin, destination, departure_date, "ow"))
        outbound = self._leg(origin, destination, departure_date, carrier,
                             duration_min, direct, hour=9)
        if return_date is None:
            price = int(base_price * market * (1 + day_jitter) * adults)
            return [self._ticket(f"ow-{carrier}-{departure_date}", (outbound,), price)]

        return_leg = self._leg(destination, origin, return_date, carrier,
                               duration_min + 15, direct, hour=18)
        day_jitter_rt = self._jitter((origin, destination, departure_date, return_date, "rt"))
        price = int((base_price * 1.7) * market * (1 + day_jitter_rt) * adults)
        return [
            self._ticket(
                f"rt-{carrier}-{departure_date}-{return_date}",
                (outbound, return_leg),
                price,
            )
        ]

    def search_multi_city(
        self, *, segments: Sequence[Segment], adults: int = 1
    ) -> list[TicketOffer]:
        if len(segments) < 2:
            return []
        seeds = [self._seed(o, d) for o, d, _ in segments]
        carrier = max(seeds, key=lambda sd: sd[0])[2]
        legs: list[FlightLeg] = []
        for (o, d, day), (_, minutes, _, direct) in zip(segments, seeds, strict=True):
            prev = legs[-1] if legs else None
            if prev and prev.destination == o and prev.arrival.date() == day:
                dep = prev.arrival + timedelta(minutes=150)  # same-ticket connection
            else:
                dep = datetime.combine(day, time(14, 0), tzinfo=UTC)
            legs.append(
                FlightLeg(
                    origin=o,
                    destination=d,
                    departure=dep,
                    arrival=dep + timedelta(minutes=minutes),
                    carrier=carrier,
                    flight_number=f"{carrier}{(hash((o, d, day)) % 900) + 100}",
                    cabin=CabinClass.ECONOMY,
                    stops=0 if direct else 1,
                )
            )

        first_origin, _, first_day = segments[0]
        hub_touches = sum(1 for o, d, _ in segments if _HUB in (o, d))
        outstation = (
            first_origin not in TW_AIRPORT_CODES and len(segments) >= 4 and hub_touches >= 4
        )
        factor = OUTSTATION_MULTI_CITY_FACTOR if outstation else MULTI_CITY_FACTOR
        jitter = self._jitter(("mc", *segments))
        price = int(
            sum(sd[0] for sd in seeds)
            * factor
            * market_factor(first_origin, first_day)
            * (1 + jitter)
            * adults
        )
        offer_id = "mc-" + "-".join(f"{o}{d}{day:%m%d}" for o, d, day in segments)
        return [self._ticket(offer_id, tuple(legs), price)]

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _seed(self, origin: str, destination: str) -> tuple[int, int, str, bool]:
        seed = self._ROUTE_SEEDS.get((origin, destination))
        if seed is not None:
            return seed
        if origin in TW_AIRPORT_CODES and destination in _SEED:
            ow, minutes, carrier = _SEED[destination]
            bump = 1.0 if origin == _HUB else 1.06
            return (round(ow * bump, -2), minutes, carrier, True)
        if destination in TW_AIRPORT_CODES and origin in _SEED:
            ow, minutes, carrier = _SEED[origin]
            bump = 0.98 if destination == _HUB else 1.04
            return (round(ow * bump, -2), minutes + 10, carrier, True)
        return (15000, 240, "ZZ", False)  # neutral synthetic route

    @staticmethod
    def _jitter(key: tuple[object, ...]) -> float:
        """Deterministic ±12% price jitter from a stable key."""
        h = hashlib.sha256(repr(key).encode()).digest()
        v = int.from_bytes(h[:2], "big") / 65535.0  # 0..1
        return (v - 0.5) * 0.24

    @staticmethod
    def _leg(
        origin: str,
        destination: str,
        day: date,
        carrier: str,
        duration_min: int,
        direct: bool,
        *,
        hour: int,
    ) -> FlightLeg:
        dep = datetime.combine(day, time(hour, 0), tzinfo=UTC)
        return FlightLeg(
            origin=origin,
            destination=destination,
            departure=dep,
            arrival=dep + timedelta(minutes=duration_min),
            carrier=carrier,
            flight_number=f"{carrier}{(hash((origin, destination, day)) % 900) + 100}",
            cabin=CabinClass.ECONOMY,
            stops=0 if direct else 1,
        )

    @staticmethod
    def _ticket(offer_id: str, legs: tuple[FlightLeg, ...], price: int) -> TicketOffer:
        return TicketOffer(
            offer_id=offer_id,
            legs=legs,
            total_price=price,
            currency="TWD",
            fare_class="Y",
            baggage_through_checked=True,
            issuer="fake",
        )


# sanity: it satisfies the Protocol
_: FlightOfferProvider = FakeFareProvider()

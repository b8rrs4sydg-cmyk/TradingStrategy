"""Deterministic stub provider for local dev + tests.

Fake prices follow a reproducible hash of (origin, destination, date, carrier)
so tests can assert stable orderings without network.

The fare model is deliberately simple but reproduces the two market effects
the 反向票 / 倒買法 / 四腿票 strategies exploit:

* Journeys that *start in Taiwan* during a Taiwan long weekend cost
  ``TW_HOLIDAY_SURGE`` more; the same dates sold from a foreign market don't.
* A multi-city journey sold from an outstation that passes through Taipei
  twice (外站四段票 X→TPE→D→TPE→X) is priced in that cheaper market at
  ``OUTSTATION_MULTI_CITY_FACTOR`` of the summed one-way fares.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import ClassVar

from app.data.airports import BY_CODE, TW_AIRPORT_CODES
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


class StubFlightProvider:
    """Reproducible pseudo-random offers; useful before real APIs are wired."""

    name: ClassVar[str] = "stub"

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
        if origin in TW_AIRPORT_CODES and destination in BY_CODE:
            a = BY_CODE[destination]
            if a.ow_from_tpe:
                bump = 1.0 if origin == _HUB else 1.06
                return (round(a.ow_from_tpe * bump, -2), a.minutes, a.carrier, True)
        if destination in TW_AIRPORT_CODES and origin in BY_CODE:
            a = BY_CODE[origin]
            if a.ow_from_tpe:
                bump = 0.98 if destination == _HUB else 1.04
                return (round(a.ow_from_tpe * bump, -2), a.minutes + 10, a.carrier, True)
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
            issuer="stub",
        )


# sanity: it satisfies the Protocol
_: FlightOfferProvider = StubFlightProvider()

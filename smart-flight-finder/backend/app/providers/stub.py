"""Deterministic stub provider for local dev + tests.

Fake prices follow a reproducible hash of (origin, destination, date, carrier)
so tests can assert stable orderings without network.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time, timedelta, timezone
from typing import ClassVar

from app.models.enums import CabinClass
from app.providers.base import FlightOfferProvider
from app.services.strategies.base import FlightLeg, TicketOffer


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
        seed = self._ROUTE_SEEDS.get((origin, destination))
        if seed is None:
            # fall back to a neutral synthetic route
            seed = (15000, 240, "ZZ", False)
        base_price, duration_min, carrier, direct = seed

        day_jitter = self._jitter((origin, destination, departure_date, "ow"))
        outbound = self._leg(origin, destination, departure_date, carrier,
                             duration_min, direct, hour=9)
        if return_date is None:
            price = int(base_price * (1 + day_jitter) * adults)
            return [self._ticket(f"ow-{carrier}-{departure_date}", (outbound,), price)]

        return_leg = self._leg(destination, origin, return_date, carrier,
                               duration_min + 15, direct, hour=18)
        day_jitter_rt = self._jitter((origin, destination, departure_date, return_date, "rt"))
        price = int((base_price * 1.7) * (1 + day_jitter_rt) * adults)
        return [
            self._ticket(
                f"rt-{carrier}-{departure_date}-{return_date}",
                (outbound, return_leg),
                price,
            )
        ]

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
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
        dep = datetime.combine(day, time(hour, 0), tzinfo=timezone.utc)
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

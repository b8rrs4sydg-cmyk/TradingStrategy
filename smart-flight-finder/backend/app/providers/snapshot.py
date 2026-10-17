"""Real fares from a Google Flights snapshot (``fares.json``).

``scripts/build_fare_snapshot.py`` (run daily by GitHub Actions) opens the
Google Flights searches the planners need and records the cheapest real
total price per query. This provider answers from that file and falls back
to another provider (the stub) for anything the snapshot doesn't cover, so
every offer says where its price came from via ``issuer``.

Google Flights lists only the first segment's flights before you pick one,
so a snapshot entry has the real total price + real first-segment times;
later segments keep the fallback's dates with carrier ``待選`` so the UI
shows "航班待選".

Key format (shared with the demo page's JS):

    ow|TPE|NRT|2027-02-05
    rt|TPE|NRT|2027-02-05|2027-02-15
    mc|HKG-TPE-2027-02-07|TPE-NRT-2027-02-07|...
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.providers.base import FlightOfferProvider, Segment
from app.providers.stub import StubFlightProvider
from app.services.strategies.base import FlightLeg, TicketOffer

ISSUER = "google_flights"
_CONNECT = timedelta(minutes=150)


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


class SnapshotFareProvider:
    name = "google_flights_snapshot"

    def __init__(
        self, snapshot: dict[str, Any], fallback: FlightOfferProvider | None = None
    ) -> None:
        self.fares: dict[str, dict[str, Any]] = snapshot.get("fares", {})
        self.generated_at: str | None = snapshot.get("generated_at")
        self.fallback = fallback or StubFlightProvider()
        self.hits = 0
        self.misses = 0

    @classmethod
    def from_path(cls, path: str | Path, fallback: FlightOfferProvider | None = None):
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), fallback)

    # ------------------------------------------------------------------
    def search(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: date,
        return_date: date | None = None,
        adults: int = 1,
    ) -> list[TicketOffer]:
        base = self.fallback.search(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
        )
        if return_date is None:
            key = fare_key([(origin, destination, departure_date)])
        else:
            key = fare_key(
                [(origin, destination, departure_date), (destination, origin, return_date)],
                round_trip=True,
            )
        return self._apply(key, base, adults)

    def search_multi_city(
        self, *, segments: Sequence[Segment], adults: int = 1
    ) -> list[TicketOffer]:
        base = self.fallback.search_multi_city(segments=segments, adults=adults)
        return self._apply(fare_key(segments), base, adults)

    # ------------------------------------------------------------------
    def _apply(self, key: str, base: list[TicketOffer], adults: int) -> list[TicketOffer]:
        entry = self.fares.get(key)
        if entry is None or not base:
            self.misses += 1
            return base
        self.hits += 1
        template = min(base, key=lambda o: o.total_price)
        legs = list(template.legs)
        first = entry.get("first")
        if first:
            legs[0] = FlightLeg(
                origin=legs[0].origin,
                destination=legs[0].destination,
                departure=datetime.fromisoformat(first["dep"]),
                arrival=datetime.fromisoformat(first["arr"]),
                carrier=first.get("airline") or legs[0].carrier,
                flight_number="",
                stops=int(first.get("stops", 0)),
            )
            # Later segments are placeholders; keep same-day connections after
            # the real first flight so connection checks stay meaningful.
            for i in range(1, len(legs)):
                prev, leg = legs[i - 1], replace(legs[i], carrier="待選", flight_number="")
                legs[i] = leg
                if leg.departure.date() <= prev.arrival.date() and leg.departure < prev.arrival + _CONNECT:
                    dep = prev.arrival + _CONNECT
                    legs[i] = replace(leg, departure=dep, arrival=dep + leg.duration)
        return [
            replace(
                template,
                offer_id=f"gf-{key}",
                legs=tuple(legs),
                total_price=int(entry["price"]) * adults,
                issuer=ISSUER,
                fare_class="後段航班待選" if len(legs) > 1 else None,
            )
        ]

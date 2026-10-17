"""Records which fare queries the planners make — never a price source.

The planners run once against this provider to learn their search list
(for the crawler and for live prefetch). Every query answers with the same
placeholder offer, so no planner prunes a branch on price and the list is
complete; nothing it returns ever reaches a user.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta

from app.providers.base import Segment
from app.providers.google_flights import fare_key
from app.services.strategies.base import FlightLeg, TicketOffer


class RecordingProvider:
    name = "recording"

    def __init__(self) -> None:
        self.keys: dict[str, None] = {}

    def search(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: date,
        return_date: date | None = None,
        adults: int = 1,
    ) -> list[TicketOffer]:
        if return_date is None:
            segs: tuple[Segment, ...] = ((origin, destination, departure_date),)
            key = fare_key(segs)
        else:
            segs = ((origin, destination, departure_date), (destination, origin, return_date))
            key = fare_key(segs, round_trip=True)
        self.keys[key] = None
        return [_placeholder(key, segs)]

    def search_multi_city(self, *, segments: Sequence[Segment], adults: int = 1) -> list[TicketOffer]:
        key = fare_key(segments)
        self.keys[key] = None
        return [_placeholder(key, tuple(segments))]


def _placeholder(key: str, segs: tuple[Segment, ...]) -> TicketOffer:
    legs: list[FlightLeg] = []
    for o, d, day in segs:
        dep = datetime.combine(day, time(8, 0), tzinfo=UTC)
        if legs and legs[-1].destination == o and dep < legs[-1].arrival + timedelta(hours=3):
            dep = legs[-1].arrival + timedelta(hours=3)
        legs.append(FlightLeg(o, d, dep, dep + timedelta(hours=2), "XX", "XX0"))
    return TicketOffer(offer_id=key, legs=tuple(legs), total_price=1)

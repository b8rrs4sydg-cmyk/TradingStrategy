"""Flight data source abstraction.

Phase 2+ 之後，Amadeus / Skyscanner adapters 會實作同一個 Protocol，
策略引擎與測試只倚賴 ``FlightOfferProvider``。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.services.strategies.base import TicketOffer

# (origin, destination, departure date) for one segment of a multi-city search.
Segment = tuple[str, str, date]


@runtime_checkable
class FlightOfferProvider(Protocol):
    """Any plug-in data source for airfare offers."""

    name: str

    def search(
        self,
        *,
        origin: str,
        destination: str,
        departure_date: date,
        return_date: date | None = None,
        adults: int = 1,
    ) -> list[TicketOffer]:
        """Return offers for a single OD + date combination.

        Must be *synchronous and side-effect free* at this layer; async
        wrapping and Redis caching happen in a higher-level service.
        """
        ...

    def search_multi_city(
        self, *, segments: Sequence[Segment], adults: int = 1
    ) -> list[TicketOffer]:
        """Price all ``segments`` as ONE ticket (e.g. 外站四段票).

        Providers whose API cannot quote multi-city fares return ``[]``;
        planners treat that as "no offer".
        """
        ...

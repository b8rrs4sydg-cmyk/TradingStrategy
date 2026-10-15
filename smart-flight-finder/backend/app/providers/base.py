"""Flight data source abstraction.

Phase 2+ 之後，Amadeus / Skyscanner adapters 會實作同一個 Protocol，
策略引擎與測試只倚賴 ``FlightOfferProvider``。
"""

from __future__ import annotations

from datetime import date
from typing import Protocol, runtime_checkable

from app.services.strategies.base import TicketOffer


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

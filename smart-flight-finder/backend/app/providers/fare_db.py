"""The fare database: real Google Flights prices, and the provider over it.

``fares.json`` is built by the crawler (``scripts/build_fare_snapshot.py``,
every 6 h on GitHub Actions) and, when live lookups are on, grows with what
``FareDatabaseProvider`` fetches on demand. It is the ONLY price source —
a query it has no entry for simply has no offer.

Schema (``schema: 2``)::

    {"schema": 2, "source": "google_flights", "generated_at": ISO-8601,
     "currency": "TWD", "adults": 1,
     "coverage": {"origins": [...], "destinations": [...], "outer_stations": [...],
                  "holidays": [...], "flex": 1, "outer_stay_days": 2},
     "fares": {KEY: {"price": 22080, "at": "2026-10-17",
                     "first": {"dep": ISO, "arr": ISO, "stops": 0, "airline": "..."},
                     "prev": 23100, "prev_at": "2026-10-16",
                     "hist": [["2026-10-16", 23100], ["2026-10-17", 22080]],
                     "separate": true}},          # only if Google had no single ticket
     "missing": [KEY, ...]}
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from app.providers.base import Segment
from app.providers.google_flights import ISSUER, fare_key, parse_key, tz_of
from app.services.strategies.base import FlightLeg, TicketOffer

logger = logging.getLogger(__name__)

SCHEMA = 2
MAX_AGE_DAYS = 7      # entries not re-fetched for a week are dropped
HISTORY_POINTS = 14   # price points kept per key
_CONNECT = timedelta(minutes=150)
_PLACEHOLDER = "待選"   # carrier of segments whose flight is picked on the site


@dataclass
class FareDatabase:
    fares: dict[str, dict[str, Any]] = field(default_factory=dict)
    generated_at: str | None = None
    coverage: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> FareDatabase:
        return cls(
            fares=dict(data.get("fares", {})),
            generated_at=data.get("generated_at"),
            coverage=dict(data.get("coverage") or data.get("config") or {}),
            missing=list(data.get("missing", [])),
        )

    @classmethod
    def load(cls, path: str | Path) -> FareDatabase:
        p = Path(path)
        return cls.from_json(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else cls()

    def to_json(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "source": ISSUER,
            "generated_at": self.generated_at,
            "currency": "TWD",
            "adults": 1,
            "coverage": self.coverage,
            "fares": dict(sorted(self.fares.items())),
            "missing": sorted(self.missing),
        }

    def save(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------
    def merge(self, fetched: dict[str, dict], *, today: date, missing: Iterable[str] = ()) -> None:
        """Upsert today's fetches, keeping price history; expire stale entries.

        A query that failed today keeps its last price while it is at most
        :data:`MAX_AGE_DAYS` old (its own ``at`` says how fresh it is);
        entries whose first flight already left are dropped.
        """

        day = today.isoformat()
        for key, new in fetched.items():
            old = self.fares.get(key, {})
            hist = [h for h in old.get("hist", []) if h[0] != day]
            if not hist and "price" in old:
                hist = [[old.get("at") or day, old["price"]]]
                hist = [h for h in hist if h[0] != day]
            hist = (hist + [[day, new["price"]]])[-HISTORY_POINTS:]
            entry = {**new, "at": day, "hist": hist}
            if len(hist) >= 2:
                entry["prev"], entry["prev_at"] = hist[-2][1], hist[-2][0]
            self.fares[key] = entry
        keep: dict[str, dict] = {}
        for key, entry in self.fares.items():
            at = entry.get("at") or (self.generated_at or day)[:10]
            fresh = (today - date.fromisoformat(at[:10])).days <= MAX_AGE_DAYS
            upcoming = parse_key(key)[1][0][2] > today
            if fresh and upcoming:
                keep[key] = {**entry, "at": at[:10]}
        self.fares = keep
        self.missing = sorted(k for k in set(missing) if k not in keep)
        self.generated_at = datetime.now(UTC).isoformat(timespec="seconds")


# --- offers -------------------------------------------------------------------
def offer_from_entry(key: str, entry: dict[str, Any], adults: int = 1) -> TicketOffer:
    """A ticket whose total is the real fare; only segment 1 has real times."""

    _, segs = parse_key(key)
    first = entry.get("first")
    legs: list[FlightLeg] = []
    for i, (o, d, day) in enumerate(segs):
        if i == 0 and first:
            legs.append(
                FlightLeg(
                    origin=o,
                    destination=d,
                    departure=datetime.fromisoformat(first["dep"]),
                    arrival=datetime.fromisoformat(first["arr"]),
                    carrier=first.get("airline") or _PLACEHOLDER,
                    flight_number="",
                    stops=int(first.get("stops", 0)),
                )
            )
            continue
        dep = datetime.combine(day, time(12, 0), tzinfo=tz_of(o))
        prev = legs[-1] if legs else None
        if prev and prev.destination == o and dep < prev.arrival + _CONNECT:
            dep = prev.arrival + _CONNECT  # same-day connection after the real flight
        # A mirrored segment takes the known flight time; others stay unknown (0).
        known = legs[0] if legs and (legs[0].origin, legs[0].destination) == (d, o) else None
        legs.append(
            FlightLeg(
                origin=o,
                destination=d,
                departure=dep,
                arrival=dep + (known.duration if known else timedelta(0)),
                carrier=_PLACEHOLDER,
                flight_number="",
            )
        )
    return TicketOffer(
        offer_id=f"gf-{key}",
        legs=tuple(legs),
        total_price=int(entry["price"]) * adults,
        currency="TWD",
        fare_class="後段航班待選" if len(legs) > 1 else None,
        issuer=ISSUER,
    )


Fetcher = Callable[[Sequence[str]], tuple[dict[str, dict], list[str]]]


class FareDatabaseProvider:
    """Answers from the fare database; optionally fetches misses live.

    ``prefetch(keys)`` is called by ``SearchService`` with every query the
    planners will make; up to ``live_budget`` missing ones are fetched from
    Google Flights in one browser session and written back to the database
    (and its file), so the database grows with what people search.
    """

    name = "google_flights_db"

    def __init__(
        self,
        db: FareDatabase,
        *,
        path: str | Path | None = None,
        fetcher: Fetcher | None = None,
        live_budget: int = 0,
    ) -> None:
        self.db = db
        self.path = Path(path) if path else None
        self.fetcher = fetcher
        self.live_budget = live_budget
        self.hits = 0
        self.misses = 0
        self.live_fetched = 0
        self._lock = threading.Lock()

    @classmethod
    def from_path(cls, path: str | Path, **kw) -> FareDatabaseProvider:
        return cls(FareDatabase.load(path), path=path, **kw)

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
        if return_date is None:
            key = fare_key([(origin, destination, departure_date)])
        else:
            key = fare_key(
                [(origin, destination, departure_date), (destination, origin, return_date)],
                round_trip=True,
            )
        return self._lookup(key, adults)

    def search_multi_city(self, *, segments: Sequence[Segment], adults: int = 1) -> list[TicketOffer]:
        return self._lookup(fare_key(segments), adults)

    def prefetch(self, keys: Iterable[str]) -> int:
        if not (self.fetcher and self.live_budget):
            return 0
        wanted = [k for k in dict.fromkeys(keys) if k not in self.db.fares]
        # cheapest pages first: one-ways and round trips, then multi-city
        wanted.sort(key=lambda k: k.startswith("mc|"))
        wanted = wanted[: self.live_budget]
        if not wanted:
            return 0
        try:
            fetched, missing = self.fetcher(wanted)
        except Exception as e:  # noqa: BLE001 — live lookups are best-effort
            logger.warning("live_fare_fetch_failed", extra={"err": str(e)})
            return 0
        with self._lock:
            self.db.merge(fetched, today=datetime.now(UTC).date(), missing=[*self.db.missing, *missing])
            if self.path:
                try:
                    self.db.save(self.path)
                except OSError as e:
                    logger.warning("fare_db_save_failed", extra={"err": str(e)})
        self.live_fetched += len(fetched)
        return len(fetched)

    # ------------------------------------------------------------------
    def _lookup(self, key: str, adults: int) -> list[TicketOffer]:
        entry = self.db.fares.get(key)
        if entry is None or entry.get("separate"):
            self.misses += 1
            return []
        self.hits += 1
        return [offer_from_entry(key, entry, adults)]

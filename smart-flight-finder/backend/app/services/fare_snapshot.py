"""Which real fares to fetch for the daily snapshot, and how to read them.

The query list is not hand-written: the real planners run against a
recording stub, so the snapshot holds exactly the searches 標準來回 /
反向票＋倒買法 / 外站四腿票 ask for in the configured scenario.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.data.taiwan_holidays_2027 import LEAVE_STRATEGIES
from app.models.enums import TicketStrategyType, TripType
from app.providers.base import Segment
from app.providers.snapshot import fare_key
from app.providers.stub import StubFlightProvider
from app.schemas.itinerary import CandidateWindowIn, ItineraryRequestIn
from app.services.search import SearchService

# Google Flights only sells ~11 months ahead; later dates return an error page.
GOOGLE_HORIZON_DAYS = 330


@dataclass
class SnapshotConfig:
    origins: list[str] = field(default_factory=lambda: ["TPE"])
    destinations: list[str] = field(default_factory=lambda: ["NRT", "KIX", "LHR"])
    outer_stations: list[str] = field(default_factory=lambda: ["HKG"])
    holidays: list[str] = field(default_factory=lambda: ["lunar_ny", "qingming", "duanwu"])
    flex: int = 1
    outer_stay_days: int = 2


class RecordingProvider(StubFlightProvider):
    """Stub prices, but remembers every query the planners make."""

    def __init__(self) -> None:
        self.keys: dict[str, None] = {}

    def search(self, *, origin, destination, departure_date, return_date=None, adults=1):
        if return_date is None:
            self.keys[fare_key([(origin, destination, departure_date)])] = None
        else:
            self.keys[
                fare_key(
                    [(origin, destination, departure_date), (destination, origin, return_date)],
                    round_trip=True,
                )
            ] = None
        return super().search(
            origin=origin,
            destination=destination,
            departure_date=departure_date,
            return_date=return_date,
            adults=adults,
        )

    def search_multi_city(self, *, segments, adults=1):
        self.keys[fare_key(segments)] = None
        return super().search_multi_city(segments=segments, adults=adults)


def build_request(cfg: SnapshotConfig, *, today: date) -> ItineraryRequestIn:
    horizon = today + timedelta(days=GOOGLE_HORIZON_DAYS)
    windows = [
        CandidateWindowIn(
            holiday_key=s.holiday_key,
            depart=s.window_start,
            return_date=s.window_end,
            depart_flex=cfg.flex,
            return_flex=cfg.flex,
        )
        for s in LEAVE_STRATEGIES
        if s.holiday_key in cfg.holidays and today < s.window_start - timedelta(days=cfg.flex)
        and s.window_end + timedelta(days=cfg.flex) <= horizon
    ]
    return ItineraryRequestIn(
        trip_type=TripType.ROUND_TRIP,
        origins=cfg.origins,
        destinations=cfg.destinations,
        strategies=[
            TicketStrategyType.STANDARD,
            TicketStrategyType.REVERSE,
            TicketStrategyType.BACK_TO_BACK_4LEG,
        ],
        back_to_back_outer_stations=cfg.outer_stations,
        outer_stay_days=cfg.outer_stay_days,
        candidate_windows=windows,
    )


def collect_queries(cfg: SnapshotConfig, *, today: date) -> list[str]:
    rec = RecordingProvider()
    SearchService(rec).run(build_request(cfg, today=today))
    horizon = today + timedelta(days=GOOGLE_HORIZON_DAYS)
    from app.providers.snapshot import parse_key

    return [k for k in rec.keys if all(today < d <= horizon for _, _, d in parse_key(k)[1])]


# --- parsing Google Flights result labels ------------------------------------
# Each result row carries an aria-label like (hl=en, curr=TWD):
#   "From 22080 New Taiwan dollars round trip total. Nonstop flight with Jetstar
#    Japan. Leaves Taiwan Taoyuan International Airport at 12:50 PM on Friday,
#    February 5 and arrives at Narita International Airport at 4:55 PM on
#    Friday, February 5. Total duration 3 hr 5 min. Select flight"

_PRICE = re.compile(r"(?:From )?([\d,]+) New Taiwan dollars")
_STOPS = re.compile(r"(Nonstop|(\d+) stops?) flight with ([^.]+?)\.")
_TIMES = re.compile(
    r"Leaves .+? at (\d{1,2}:\d{2}\s?[AP]M) on \w+, (\w+ \d{1,2}) and arrives at .+? at "
    r"(\d{1,2}:\d{2}\s?[AP]M) on \w+, (\w+ \d{1,2})"
)


@dataclass(frozen=True)
class ParsedOption:
    price: int
    stops: int
    airline: str
    dep: datetime | None
    arr: datetime | None


def _when(clock: str, month_day: str, year: int, tz: ZoneInfo) -> datetime:
    clock = clock.replace(" ", " ").replace(" ", "")
    dt = datetime.strptime(f"{month_day} {year} {clock}", "%B %d %Y %I:%M%p")  # noqa: DTZ007
    return dt.replace(tzinfo=tz)


def parse_option(label: str, *, year: int, dep_tz: ZoneInfo, arr_tz: ZoneInfo) -> ParsedOption | None:
    label = label.replace(" ", " ").replace("\xa0", " ")
    m = _PRICE.search(label)
    if not m:
        return None
    s = _STOPS.search(label)
    t = _TIMES.search(label)
    dep = arr = None
    if t:
        dep = _when(t.group(1), t.group(2), year, dep_tz)
        arr = _when(t.group(3), t.group(4), year, arr_tz)
        if arr < dep - timedelta(hours=14):  # crossed new year
            arr = arr.replace(year=year + 1)
    return ParsedOption(
        price=int(m.group(1).replace(",", "")),
        stops=0 if not s or s.group(1) == "Nonstop" else int(s.group(2)),
        airline=s.group(3).strip() if s else "",
        dep=dep,
        arr=arr,
    )


def cheapest_entry(
    labels: Sequence[str], segments: Sequence[Segment], tz_of
) -> dict | None:
    """Snapshot entry from a results page: cheapest total + its first segment."""

    o, d, day = segments[0]
    options = [
        p
        for lab in labels
        if (p := parse_option(lab, year=day.year, dep_tz=tz_of(o), arr_tz=tz_of(d)))
    ]
    if not options:
        return None
    best = min(options, key=lambda p: p.price)
    entry: dict = {"price": best.price}
    if best.dep and best.arr:
        entry["first"] = {
            "dep": best.dep.isoformat(),
            "arr": best.arr.isoformat(),
            "stops": best.stops,
            "airline": best.airline,
        }
    return entry


MAX_CARRY_DAYS = 7


def carry_over(
    fares: dict[str, dict], missing: list[str], previous: dict, *, today: date
) -> tuple[dict[str, dict], list[str]]:
    """Keep last snapshot's fare for a query that failed today (≤ 7 days old).

    Google Flights multi-city pages are slow and sometimes time out; an
    entry keeps its own ``at`` date so the UI can show how fresh it is.
    """

    old = previous.get("fares", {})
    fallback_day = (previous.get("generated_at") or "")[:10]
    out = dict(fares)
    still: list[str] = []
    for key in missing:
        entry = old.get(key)
        at = (entry or {}).get("at") or fallback_day
        if entry and at and (today - date.fromisoformat(at)).days <= MAX_CARRY_DAYS:
            out[key] = {**entry, "at": at}
        else:
            still.append(key)
    return dict(sorted(out.items())), sorted(still)

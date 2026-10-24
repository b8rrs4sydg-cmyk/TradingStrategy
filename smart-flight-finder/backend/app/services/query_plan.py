"""The planners' fare queries as a plan: unique, counted, and ordered for a limited live budget.

The planners are run once on :class:`RecordingProvider`, which counts how often each query was asked (a fare many
candidates share is worth more than one only a single candidate needs). :func:`prioritize` then picks which of the
missing fares to fetch live when the budget is smaller than the plan — not "the first N in enumeration order", which
spent the whole budget on whatever route happened to be listed first:

* cheap pages before expensive ones (one-way / round trip before multi-city),
* within that, the fares most candidates depend on first,
* routes (metro-normalised origin→destination) take turns, so every route gets some of the budget.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from datetime import date

from app.data.metro import route_key
from app.providers.google_flights import parse_key
from app.providers.recording import RecordingProvider


def required_queries(run: Callable[[RecordingProvider], object]) -> dict[str, int]:
    """The single way to learn what the planners will ask: run them once on a recorder, get query -> times asked.

    ``run`` receives the recorder and drives the planners with it (``SearchService`` for a live search, the crawl plan
    for the crawler), so both consumers share one definition of "the plan" instead of each re-implementing the dry run.
    """

    rec = RecordingProvider()
    run(rec)
    return rec.keys


def kind_of(key: str) -> str:
    return key.split("|", 1)[0]


def route_of(key: str) -> tuple[str, str]:
    """Metro-normalised (origin, destination) of the first segment, direction-free: a return leg belongs to its route."""

    kind, rest = key.split("|", 1)
    if kind == "mc":
        first = rest.split("|", 1)[0]  # O-D-YYYY-MM-DD
        o, d = first.split("-")[:2]
    else:
        o, d = rest.split("|")[:2]
    a, b = route_key(o), route_key(d)
    return (a, b) if a <= b else (b, a)


def prioritize(
    keys: Iterable[str] | Mapping[str, int],
    budget: int,
    *,
    known: Iterable[str] = (),
    promise_of: Callable[[str], float | None] | None = None,
) -> list[str]:
    """At most ``budget`` keys, best first; keys in ``known`` (already priced) are skipped.

    ``promise_of(key)`` (see :func:`promise`) orders the expensive multi-city pages by how likely they are to save
    anything: hopeful ones first (smaller is better), unknown ones in the middle, those that cannot beat the baseline even
    at their floor (>= 1) last — they are only fetched when the budget outlasts everything else.
    """

    have = set(known)
    counts: Mapping[str, int] = keys if isinstance(keys, Mapping) else dict.fromkeys(keys, 1)
    todo = [k for k in counts if k not in have]
    if budget <= 0 or not todo:
        return []
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for k in todo:
        groups[route_of(k)].append(k)
    def rank(k: str) -> float:
        p = promise_of(k) if promise_of else None
        if p is None:
            return 0.75  # nothing known yet: after the hopeful ones, before the hopeless
        return p / 2 if p < 1 else 1 + min(p, 1e6)

    for g in groups.values():
        g.sort(key=lambda k: (kind_of(k) == "mc", rank(k) if kind_of(k) == "mc" else 0, -(counts[k] or 1), k))
    # turn by turn: the best remaining fare of each route, routes with the most-wanted fare first
    order = sorted(
        groups.values(), key=lambda g: (kind_of(g[0]) == "mc", -(counts[g[0]] or 1), g[0])
    )
    picked: list[str] = []
    i = 0
    while len(picked) < budget and i < max(len(g) for g in order):
        for g in order:
            if i < len(g):
                picked.append(g[i])
                if len(picked) >= budget:
                    break
        i += 1
    return picked


# --- how promising a multi-city fare is, from fares already known -----------------------------------------------
SCREEN_FACTOR = 0.95  # floor = this share of the sum of the legs' one-way fares (real fares: multi-city >= 1.04 x that sum)


def _min_price(prices: Mapping[str, int], prefix: str, ok) -> int | None:
    vals = [p for k, p in prices.items() if k.startswith(prefix) and ok(k)]
    return min(vals) if vals else None


def _near(day: date, flex: int):
    def ok(key: str) -> bool:
        return abs((parse_key(key)[1][0][2] - day).days) <= flex + 1

    return ok


def four_leg_room_for(key: str, prices: Mapping[str, int], flex: int) -> tuple[float | None, int | None, tuple]:
    """(money the four-leg ticket may cost and still save, trip-Q round trip, group) for a 四腿票 key.

    The four-leg ticket replaces three round trips (X on P, D on Q, Y on R); the 單買初段 and 最後一段 are bought
    separately, so what it may cost at most to beat them is rt(X) + rt(D) + rt(Y) - ow(TPE->X) - ow(Y->TPE).
    """

    _, segs = parse_key(key)
    (x, _, c1), (_, d, c2), _, (_, y, r_dep) = segs
    group = ("4leg", x, d, y, c1.month, c2.month, r_dep.month)
    ow_first = _min_price(prices, f"ow|TPE|{x}|", lambda k: parse_key(k)[1][0][2] < c1)
    ow_last = _min_price(prices, f"ow|{y}|TPE|", lambda k: parse_key(k)[1][0][2] > r_dep)
    rt_x = _min_price(prices, f"rt|TPE|{x}|", lambda k: abs((parse_key(k)[1][1][2] - c1).days) <= flex + 1)
    rt_d = _min_price(prices, f"rt|TPE|{d}|", _near(c2, flex))
    rt_y = _min_price(prices, f"rt|TPE|{y}|", _near(r_dep, flex))
    if None in (ow_first, ow_last, rt_x, rt_d, rt_y):
        return None, None, group
    return rt_x + rt_d + rt_y - ow_first - ow_last, rt_d, group


def promise(key: str, prices: Mapping[str, int], flex: int = 1) -> float | None:
    """How much of its saving room a four-leg ticket would already use up at its cheapest possible fare.

    ``floor / room`` where floor = 0.95 x the sum of the legs' known one-way fares and room = the most the ticket may
    cost and still beat three round trips. Below 1 there is room to save (smaller = more hopeful, P(c) is high);
    1 or more: even at the floor it cannot save. None when a leg or a baseline fare is not known yet.
    """

    kind, segs = key.split("|", 1)[0], None
    if kind != "mc":
        return None
    segs = parse_key(key)[1]
    if len(segs) != 4:
        return None
    room, _, _ = four_leg_room_for(key, prices, flex)
    legs = [prices.get(f"ow|{o}|{d}|{day.isoformat()}") for o, d, day in segs]
    if room is None or room <= 0 or None in legs:
        return None if room is None or None in legs else float("inf")
    return SCREEN_FACTOR * sum(legs) / room

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

from app.data.metro import route_key
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
    keys: Iterable[str] | Mapping[str, int], budget: int, *, known: Iterable[str] = ()
) -> list[str]:
    """At most ``budget`` keys, best first; keys in ``known`` (already priced) are skipped."""

    have = set(known)
    counts: Mapping[str, int] = keys if isinstance(keys, Mapping) else dict.fromkeys(keys, 1)
    todo = [k for k in counts if k not in have]
    if budget <= 0 or not todo:
        return []
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for k in todo:
        groups[route_of(k)].append(k)
    for g in groups.values():
        g.sort(key=lambda k: (kind_of(k) == "mc", -(counts[k] or 1), k))
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

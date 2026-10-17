"""Shared pieces for strategies that span TWO trips (two 備選時段).

反向票 + 倒買法 and 外站四腿票 only pay off when one purchase covers two
separate trips, so their planners take an ordered pair of trip slots
(A strictly before B) instead of a single date window.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import TypeVar

from app.providers.base import FlightOfferProvider, Segment
from app.services.strategies.base import TicketOffer

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class TripSlot:
    label: str
    departs: tuple[date, ...]   # candidate departure-from-home dates
    returns: tuple[date, ...]   # candidate return-home dates


def cheapest(offers: Sequence[TicketOffer]) -> TicketOffer | None:
    return min(offers, key=lambda o: o.total_price) if offers else None


def quote(
    provider: FlightOfferProvider, segments: Sequence[Segment], adults: int
) -> TicketOffer | None:
    """Cheapest single ticket covering ``segments``, tagged with them.

    Two mirrored segments are asked as a plain round trip (every provider can
    price that); anything else goes through ``search_multi_city``.
    """

    segs = tuple(segments)
    if len(segs) == 1:
        (o, d, day), = segs
        t = cheapest(provider.search(origin=o, destination=d, departure_date=day, adults=adults))
    elif len(segs) == 2 and segs[0][0] == segs[1][1] and segs[0][1] == segs[1][0]:
        t = cheapest(
            provider.search(
                origin=segs[0][0],
                destination=segs[0][1],
                departure_date=segs[0][2],
                return_date=segs[1][2],
                adults=adults,
            )
        )
    else:
        t = cheapest(provider.search_multi_city(segments=segs, adults=adults))
    return replace(t, searched_segments=segs) if t else None


def best_pair(
    front: Sequence[tuple[int, T]],
    back: Sequence[tuple[int, T]],
    compatible: Callable[[T, T], bool],
) -> tuple[int, T, T] | None:
    """Cheapest (front, back) combination satisfying ``compatible``.

    Both lists are scanned in price order with early exit, so the common case
    (cheapest options are compatible) is O(n log n).
    """

    f_sorted = sorted(front, key=lambda x: x[0])
    b_sorted = sorted(back, key=lambda x: x[0])
    if not f_sorted or not b_sorted:
        return None
    best: tuple[int, T, T] | None = None
    for fc, fv in f_sorted:
        if best and fc + b_sorted[0][0] >= best[0]:
            break
        for bc, bv in b_sorted:
            if best and fc + bc >= best[0]:
                break
            if compatible(fv, bv):
                best = (fc + bc, fv, bv)
                break
    return best


def nearest(dates: Sequence[date], k: int) -> tuple[date, ...]:
    """The ``k`` candidates closest to the window's centre (its anchor)."""

    if len(dates) <= k:
        return tuple(dates)
    mid = dates[len(dates) // 2]
    return tuple(sorted(sorted(dates, key=lambda d: abs((d - mid).days))[:k]))


def fmt_day(d: date) -> str:
    return f"{d.month}/{d.day}"

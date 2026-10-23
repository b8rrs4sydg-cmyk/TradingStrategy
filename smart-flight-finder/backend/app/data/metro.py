"""Metropolitan areas and ground transfers between airports (used to judge Open Jaw pairs).

"Same country" is not "reasonable": 大阪進、沖繩出 needs a flight. Each airport maps to a metro area; a pair is graded

* ``SAME_METRO`` (tier 1)    — alternative airports of one city (HND/NRT, KIX/ITM/UKB): a short transfer,
* ``GROUND``     (tier 2)    — different cities joined by a listed rail/bus link (東京 ⇄ 大阪): time and cost known,
* ``SEPARATE``   (tier 3)    — no listed ground link, or an island hop (大阪 ⇄ 沖繩): needs another flight,
* ``UNKNOWN``    (tier 4)    — an airport we have no metro data for: unverified, never recommended as an ordinary open jaw.

Costs are rough 2026 TWD figures for planning, not quotes; extend ``METRO_OF`` / ``GROUND`` as data is verified.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

METRO_OF: dict[str, str] = {
    **dict.fromkeys(("HND", "NRT"), "TYO"),
    **dict.fromkeys(("KIX", "ITM", "UKB"), "OSA"),
    **dict.fromkeys(("NGO", "NKM"), "NGO"),
    **dict.fromkeys(("FUK", "KKJ"), "FUK"),
    **dict.fromkeys(("CTS",), "SPK"),
    **dict.fromkeys(("OKA", "ISG", "MMY"), "OKA"),
    **dict.fromkeys(("ICN", "GMP"), "SEL"),
    **dict.fromkeys(("PUS",), "PUS"),
    **dict.fromkeys(("BKK", "DMK"), "BKK"),
    **dict.fromkeys(("SGN",), "SGN"),
    **dict.fromkeys(("HAN",), "HAN"),
    **dict.fromkeys(("PVG", "SHA"), "SHA"),
    **dict.fromkeys(("PEK", "PKX"), "BJS"),
    **dict.fromkeys(("TPE", "TSA"), "TPE"),
}

# (metro, metro) -> (minutes, TWD) for a sensible land link; symmetric
GROUND: dict[frozenset[str], tuple[int, int]] = {
    frozenset(("TYO", "OSA")): (150, 4200),  # shinkansen
    frozenset(("OSA", "NGO")): (50, 1500),
    frozenset(("TYO", "NGO")): (100, 3300),
    frozenset(("SEL", "PUS")): (150, 1700),  # KTX
    frozenset(("SHA", "BJS")): (270, 2000),
}
SAME_METRO_TRANSFER = (75, 400)  # airport ↔ airport inside a metro: minutes, TWD


class Tier(IntEnum):
    SAME_METRO = 1
    GROUND = 2
    SEPARATE = 3
    UNKNOWN = 4


@dataclass(frozen=True)
class Transfer:
    tier: Tier
    minutes: int | None
    cost_twd: int | None


def metro_of(code: str) -> str | None:
    return METRO_OF.get(code)


def route_key(code: str) -> str:
    """Metro when known, else the airport itself (so unknown airports never merge)."""

    return METRO_OF.get(code, code)


def transfer(a: str, b: str) -> Transfer:
    ma, mb = METRO_OF.get(a), METRO_OF.get(b)
    if ma is None or mb is None:
        return Transfer(Tier.UNKNOWN, None, None)
    if ma == mb:
        return Transfer(Tier.SAME_METRO, *SAME_METRO_TRANSFER)
    link = GROUND.get(frozenset((ma, mb)))
    if link is None:
        return Transfer(Tier.SEPARATE, None, None)
    return Transfer(Tier.GROUND, *link)

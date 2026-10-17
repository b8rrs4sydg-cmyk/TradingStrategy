"""Airport catalog for the search form checkboxes and the stub fare table.

``ow_from_tpe`` is an illustrative one-way economy fare (TWD) from Taipei used
only by :class:`StubFlightProvider`; real providers ignore it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Airport:
    code: str
    name_zh: str
    country: str        # ISO-2
    group: str          # UI grouping
    ow_from_tpe: int    # stub fare, TWD
    minutes: int        # stub block time from TPE
    carrier: str        # stub operating carrier
    outstation: bool = False  # commonly used as a 四腿票 外站 (leg 1 / leg 4)


TW_ORIGINS: tuple[Airport, ...] = (
    Airport("TPE", "台北桃園", "TW", "台灣", 0, 0, "BR"),
    Airport("TSA", "台北松山", "TW", "台灣", 0, 0, "CI"),
    Airport("KHH", "高雄", "TW", "台灣", 0, 0, "CI"),
    Airport("RMQ", "台中", "TW", "台灣", 0, 0, "AE"),
)

DESTINATIONS: tuple[Airport, ...] = (
    Airport("NRT", "東京成田", "JP", "日本", 12800, 190, "BR", True),
    Airport("HND", "東京羽田", "JP", "日本", 14200, 185, "CI", True),
    Airport("KIX", "大阪關西", "JP", "日本", 11800, 180, "JX", True),
    Airport("NGO", "名古屋", "JP", "日本", 11500, 175, "CI"),
    Airport("FUK", "福岡", "JP", "日本", 10200, 150, "CI", True),
    Airport("CTS", "札幌", "JP", "日本", 13800, 245, "BR"),
    Airport("OKA", "沖繩", "JP", "日本", 8200, 90, "CI"),
    Airport("ICN", "首爾仁川", "KR", "韓國", 9800, 160, "KE", True),
    Airport("PUS", "釜山", "KR", "韓國", 9200, 135, "BR"),
    Airport("HKG", "香港", "HK", "港澳/中國", 5100, 90, "CX", True),
    Airport("MFM", "澳門", "MO", "港澳/中國", 5300, 95, "NX", True),
    Airport("XMN", "廈門", "CN", "港澳/中國", 4100, 90, "MF", True),
    Airport("BKK", "曼谷", "TH", "東南亞", 10800, 230, "TG", True),
    Airport("CNX", "清邁", "TH", "東南亞", 11200, 245, "BR"),
    Airport("SGN", "胡志明市", "VN", "東南亞", 8900, 215, "BR", True),
    Airport("HAN", "河內", "VN", "東南亞", 9300, 200, "CI", True),
    Airport("MNL", "馬尼拉", "PH", "東南亞", 7800, 140, "PR", True),
    Airport("CEB", "宿霧", "PH", "東南亞", 8600, 170, "JX", True),
    Airport("KUL", "吉隆坡", "MY", "東南亞", 10200, 285, "MH", True),
    Airport("SIN", "新加坡", "SG", "東南亞", 11600, 280, "SQ", True),
    Airport("LHR", "倫敦", "GB", "歐洲", 32000, 845, "BR"),
    Airport("CDG", "巴黎", "FR", "歐洲", 31500, 830, "BR"),
    Airport("AMS", "阿姆斯特丹", "NL", "歐洲", 30500, 820, "CI"),
    Airport("VIE", "維也納", "AT", "歐洲", 30000, 790, "BR"),
    Airport("LAX", "洛杉磯", "US", "美洲", 26500, 720, "BR"),
    Airport("SFO", "舊金山", "US", "美洲", 25800, 690, "BR"),
    Airport("JFK", "紐約", "US", "美洲", 30800, 935, "BR"),
    Airport("YVR", "溫哥華", "CA", "美洲", 24500, 650, "BR"),
    Airport("SYD", "雪梨", "AU", "紐澳", 22800, 555, "CI"),
    Airport("BNE", "布里斯本", "AU", "紐澳", 21900, 520, "BR"),
)

BY_CODE: dict[str, Airport] = {a.code: a for a in TW_ORIGINS + DESTINATIONS}
TW_AIRPORT_CODES: frozenset[str] = frozenset(a.code for a in TW_ORIGINS) | {
    "TNN", "HUN", "KNH", "MZG", "TTT", "HCN",
}
OUTSTATIONS: tuple[Airport, ...] = tuple(a for a in DESTINATIONS if a.outstation)

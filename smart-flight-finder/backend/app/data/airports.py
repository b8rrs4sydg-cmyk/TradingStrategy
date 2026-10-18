"""Airport catalog for the search form checkboxes (prices come only from
the Google Flights fare database, never from here)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Airport:
    code: str
    name_zh: str
    country: str        # ISO-2
    group: str          # UI grouping
    outstation: bool = False  # commonly used as a 四腿票 外站 (leg 1 / leg 4)


TW_ORIGINS: tuple[Airport, ...] = (
    Airport("TPE", "台北桃園", "TW", "台灣"),
    Airport("TSA", "台北松山", "TW", "台灣"),
    Airport("KHH", "高雄", "TW", "台灣"),
    Airport("RMQ", "台中", "TW", "台灣"),
)

DESTINATIONS: tuple[Airport, ...] = (
    Airport("NRT", "東京成田", "JP", "日本", True),
    Airport("HND", "東京羽田", "JP", "日本", True),
    Airport("KIX", "大阪關西", "JP", "日本", True),
    Airport("NGO", "名古屋", "JP", "日本"),
    Airport("FUK", "福岡", "JP", "日本", True),
    Airport("CTS", "札幌", "JP", "日本"),
    Airport("OKA", "沖繩", "JP", "日本"),
    Airport("ICN", "首爾仁川", "KR", "韓國", True),
    Airport("PUS", "釜山", "KR", "韓國"),
    Airport("HKG", "香港", "HK", "港澳/中國", True),
    Airport("MFM", "澳門", "MO", "港澳/中國", True),
    Airport("XMN", "廈門", "CN", "港澳/中國", True),
    Airport("BKK", "曼谷", "TH", "東南亞", True),
    Airport("CNX", "清邁", "TH", "東南亞"),
    Airport("SGN", "胡志明市", "VN", "東南亞", True),
    Airport("HAN", "河內", "VN", "東南亞", True),
    Airport("MNL", "馬尼拉", "PH", "東南亞", True),
    Airport("CEB", "宿霧", "PH", "東南亞", True),
    Airport("KUL", "吉隆坡", "MY", "東南亞", True),
    Airport("SIN", "新加坡", "SG", "東南亞", True),
    Airport("LHR", "倫敦", "GB", "歐洲"),
    Airport("CDG", "巴黎", "FR", "歐洲"),
    Airport("AMS", "阿姆斯特丹", "NL", "歐洲"),
    Airport("VIE", "維也納", "AT", "歐洲"),
    Airport("LAX", "洛杉磯", "US", "美洲"),
    Airport("SFO", "舊金山", "US", "美洲"),
    Airport("JFK", "紐約", "US", "美洲"),
    Airport("YVR", "溫哥華", "CA", "美洲"),
    Airport("SYD", "雪梨", "AU", "紐澳"),
    Airport("BNE", "布里斯本", "AU", "紐澳"),
)

BY_CODE: dict[str, Airport] = {a.code: a for a in TW_ORIGINS + DESTINATIONS}
TW_AIRPORT_CODES: frozenset[str] = frozenset(a.code for a in TW_ORIGINS) | {
    "TNN", "HUN", "KNH", "MZG", "TTT", "HCN",
}
OUTSTATIONS: tuple[Airport, ...] = tuple(a for a in DESTINATIONS if a.outstation)

# IANA time zones, for reading local departure/arrival times off fare sites.
TIMEZONES: dict[str, str] = {
    "TPE": "Asia/Taipei", "TSA": "Asia/Taipei", "KHH": "Asia/Taipei", "RMQ": "Asia/Taipei",
    "NRT": "Asia/Tokyo", "HND": "Asia/Tokyo", "KIX": "Asia/Tokyo", "NGO": "Asia/Tokyo",
    "FUK": "Asia/Tokyo", "CTS": "Asia/Tokyo", "OKA": "Asia/Tokyo",
    "ICN": "Asia/Seoul", "PUS": "Asia/Seoul",
    "HKG": "Asia/Hong_Kong", "MFM": "Asia/Macau", "XMN": "Asia/Shanghai",
    "BKK": "Asia/Bangkok", "CNX": "Asia/Bangkok", "SGN": "Asia/Ho_Chi_Minh",
    "HAN": "Asia/Ho_Chi_Minh", "MNL": "Asia/Manila", "CEB": "Asia/Manila",
    "KUL": "Asia/Kuala_Lumpur", "SIN": "Asia/Singapore",
    "LHR": "Europe/London", "CDG": "Europe/Paris", "AMS": "Europe/Amsterdam",
    "VIE": "Europe/Vienna", "LAX": "America/Los_Angeles", "SFO": "America/Los_Angeles",
    "JFK": "America/New_York", "YVR": "America/Vancouver",
    "SYD": "Australia/Sydney", "BNE": "Australia/Brisbane",
}

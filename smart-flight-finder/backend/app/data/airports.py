"""Airport catalog for the search form checkboxes (prices come only from
the Google Flights fare database, never from here)."""

from __future__ import annotations

from dataclasses import dataclass

from app.data.asia_airports import ASIA_AIRPORTS
from app.data.asia_airports import GROUPS as ASIA_GROUPS


@dataclass(frozen=True, slots=True)
class Airport:
    code: str
    name_zh: str
    country: str        # ISO-2
    group: str          # UI grouping
    outstation: bool = False  # commonly used as a 四腿票 外站 (leg 1 / leg 4)


# Outside Asia: only the few long-haul places the demo has always offered.
_OTHER: tuple[Airport, ...] = (
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
_OTHER_TIMEZONES: dict[str, str] = {
    "LHR": "Europe/London", "CDG": "Europe/Paris", "AMS": "Europe/Amsterdam", "VIE": "Europe/Vienna",
    "LAX": "America/Los_Angeles", "SFO": "America/Los_Angeles", "JFK": "America/New_York",
    "YVR": "America/Vancouver", "SYD": "Australia/Sydney", "BNE": "Australia/Brisbane",
}

_ASIA: tuple[Airport, ...] = tuple(
    Airport(code, name, country, group, gateway) for code, name, country, _tz, group, gateway in ASIA_AIRPORTS
)

#: Taiwan airports (出發機場): the whole Taiwan group of the catalog.
TW_ORIGINS: tuple[Airport, ...] = tuple(a for a in _ASIA if a.country == "TW")

#: Everything else, group by group (Asia in catalog order, then Europe / Americas / Oceania).
DESTINATIONS: tuple[Airport, ...] = tuple(a for a in _ASIA if a.country != "TW") + _OTHER

#: Group names in display order (Taiwan first).
GROUPS: tuple[str, ...] = (*ASIA_GROUPS, "歐洲", "美洲", "紐澳")

BY_CODE: dict[str, Airport] = {a.code: a for a in TW_ORIGINS + DESTINATIONS}
TW_AIRPORT_CODES: frozenset[str] = frozenset(a.code for a in TW_ORIGINS)
OUTSTATIONS: tuple[Airport, ...] = tuple(a for a in DESTINATIONS if a.outstation)

# IANA time zones, for reading local departure/arrival times off fare sites.
TIMEZONES: dict[str, str] = {code: tz for code, _n, _c, tz, _g, _o in ASIA_AIRPORTS} | _OTHER_TIMEZONES

#: 中文國名 (ISO-2 → name): only used to make the airport pickers searchable by country.
COUNTRY_ZH: dict[str, str] = {
    "TW": "台灣", "JP": "日本", "KR": "韓國", "HK": "香港", "MO": "澳門", "CN": "中國", "TH": "泰國", "VN": "越南",
    "PH": "菲律賓", "MY": "馬來西亞", "SG": "新加坡", "ID": "印尼", "KH": "柬埔寨", "LA": "寮國", "MM": "緬甸",
    "BN": "汶萊", "TL": "東帝汶", "IN": "印度", "PK": "巴基斯坦", "BD": "孟加拉", "LK": "斯里蘭卡", "NP": "尼泊爾",
    "BT": "不丹", "MV": "馬爾地夫", "AF": "阿富汗", "MN": "蒙古", "UZ": "烏茲別克", "KZ": "哈薩克", "KG": "吉爾吉斯",
    "TJ": "塔吉克", "TM": "土庫曼", "AE": "阿聯", "QA": "卡達", "SA": "沙烏地阿拉伯", "KW": "科威特", "BH": "巴林",
    "OM": "阿曼", "IL": "以色列", "JO": "約旦", "LB": "黎巴嫩", "IR": "伊朗", "IQ": "伊拉克", "SY": "敘利亞",
    "GE": "喬治亞", "AM": "亞美尼亞", "AZ": "亞塞拜然", "TR": "土耳其", "GB": "英國", "FR": "法國", "NL": "荷蘭",
    "AT": "奧地利", "US": "美國", "CA": "加拿大", "AU": "澳洲",
}

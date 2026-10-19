"""The Asian airport catalog and its copy inside the demo page."""

import re
from collections import Counter
from zoneinfo import ZoneInfo

import pytest

from app.data.airports import (
    BY_CODE,
    COUNTRY_ZH,
    DESTINATIONS,
    GROUPS,
    OUTSTATIONS,
    TIMEZONES,
    TW_AIRPORT_CODES,
    TW_ORIGINS,
)
from app.data.asia_airports import ASIA_AIRPORTS


def test_codes_are_unique_well_formed_and_known_everywhere():
    codes = [a[0] for a in ASIA_AIRPORTS]
    assert not [c for c, n in Counter(codes).items() if n > 1]
    for code, name, country, tz, group, _ in ASIA_AIRPORTS:
        assert re.fullmatch(r"[A-Z]{3}", code) and re.fullmatch(r"[A-Z]{2}", country) and name
        assert group in GROUPS
        ZoneInfo(tz)  # raises for an unknown IANA zone
        assert code in BY_CODE and TIMEZONES[code] == tz


def test_the_catalog_covers_taiwan_china_and_the_rest_of_asia():
    by_country = Counter(a[2] for a in ASIA_AIRPORTS)
    assert len(ASIA_AIRPORTS) >= 250
    assert by_country["TW"] >= 15 and by_country["CN"] >= 40
    for country in (
        "JP",
        "KR",
        "HK",
        "MO",
        "TH",
        "VN",
        "PH",
        "MY",
        "SG",
        "ID",
        "KH",
        "LA",
        "MM",
        "IN",
        "PK",
        "BD",
        "LK",
        "NP",
        "MV",
        "MN",
        "KZ",
        "UZ",
        "AE",
        "QA",
        "SA",
        "IL",
        "TR",
    ):
        assert by_country[country] >= 1, country


def test_taiwan_airports_are_the_origins_and_nothing_else_is():
    assert {a.code for a in TW_ORIGINS} == TW_AIRPORT_CODES
    assert {
        "TPE",
        "TSA",
        "KHH",
        "RMQ",
        "TNN",
        "CYI",
        "HUN",
        "TTT",
        "MZG",
        "KNH",
    } <= TW_AIRPORT_CODES
    assert not TW_AIRPORT_CODES & {a.code for a in DESTINATIONS}
    assert all(a.country == "TW" for a in TW_ORIGINS)


def test_outstations_are_foreign_gateways():
    assert OUTSTATIONS and all(a.country != "TW" for a in OUTSTATIONS)
    assert {"HKG", "ICN", "BKK", "NRT"} <= {a.code for a in OUTSTATIONS}


def test_urumqi_is_on_its_own_clock_and_indonesia_has_three():
    assert TIMEZONES["URC"] == "Asia/Urumqi" and TIMEZONES["PEK"] == "Asia/Shanghai"
    assert {TIMEZONES[c] for c in ("CGK", "DPS", "DJJ")} == {
        "Asia/Jakarta",
        "Asia/Makassar",
        "Asia/Jayapura",
    }


@pytest.mark.parametrize(
    "code,offset", [("TPE", "+08:00"), ("KTM", "+05:45"), ("DEL", "+05:30"), ("DXB", "+04:00")]
)
def test_standard_offsets_for_the_page(code, offset):
    from scripts.embed_airports import utc_offset

    assert utc_offset(code) == offset


def test_the_demo_page_carries_the_same_table():
    from scripts.embed_airports import PAGE

    if "AIRPORT-TABLE:START" not in PAGE.read_text(encoding="utf-8"):
        pytest.skip("the page has no airport-table block yet")
    import subprocess
    import sys

    done = subprocess.run(
        [sys.executable, "-m", "scripts.embed_airports", "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_every_country_has_a_chinese_name_for_searching():
    assert {a.country for a in BY_CODE.values()} <= set(COUNTRY_ZH)

"""Plain-HTTP Google Flights reader: parsing of the two answer shapes and the multi-city request body."""

import json
from datetime import date
from urllib.parse import parse_qs

from app.providers.google_flights import parse_key
from app.providers.google_http import (
    entry_from,
    html_payloads,
    itineraries,
    multi_city_body,
    rpc_payloads,
)


def _row(price: int, dep=(2027, 4, 3), airline="EVA Air") -> list:
    leg = [None] * 22
    leg[8], leg[10] = [8, 30], [12]  # a whole hour comes as [h]
    leg[20], leg[21] = list(dep), list(dep)
    return [[None, [airline], [leg], None], [[None, price], "token"]]


def test_itineraries_skip_price_graph_pairs():
    graph = [
        [[None, 1500], "t"],
        [[None, 1600], "t"],
    ]  # [[None, x], token]: no price one level deeper
    rows = [_row(9000), _row(8000)]
    assert [r[1][0][1] for r in itineraries([graph, [rows]])] == [9000, 8000]


def test_html_answer_gives_cheapest_row_and_first_slice():
    data = json.dumps([None, None, [[_row(9000), _row(8100)]]])
    html = f"<html>AF_initDataCallback({{key: 'ds:1', hash: '2', data:{data}, sideChannel: {{}}}});</html>"
    segs = parse_key("ow|TPE|NRT|2027-04-03")[1]
    entry = entry_from(html_payloads(html), segs)
    assert entry["price"] == 8100
    assert entry["first"]["airline"] == "EVA Air"
    assert entry["first"]["dep"].startswith("2027-04-03T08:30:00+08:00")
    assert entry["first"]["arr"].startswith("2027-04-03T12:00:00+09:00")
    assert entry["first"]["stops"] == 0


def test_page_without_flight_data_is_unknown_not_a_price():
    html = "AF_initDataCallback({key: 'ds:1', hash: '2', data:[[[null,1500],[null,1600]]], sideChannel: {}});"
    assert entry_from(html_payloads(html), parse_key("ow|TPE|NRT|2027-04-03")[1]) is None


def test_rpc_answer_is_unwrapped():
    inner = json.dumps([[_row(55330)]])
    line = json.dumps([["wrb.fr", None, inner]])
    text = f')]}}\'\n\n{len(line)}\n{line}\n25\n[["e",4,null,null,92]]\n'
    segs = parse_key(
        "mc|BKK-TPE-2027-02-06|TPE-ICN-2027-02-06|ICN-TPE-2027-02-16|TPE-HKG-2027-04-02"
    )[1]
    assert entry_from(rpc_payloads(text), segs)["price"] == 55330


def test_multi_city_body_lists_every_leg_in_order():
    segs = parse_key(
        "mc|BKK-TPE-2027-02-06|TPE-ICN-2027-02-06|ICN-TPE-2027-02-16|TPE-HKG-2027-04-02"
    )[1]
    body = multi_city_body(segs)
    assert body.startswith("f.req=") and body.endswith("&")
    inner = json.loads(json.loads(parse_qs(body)["f.req"][0])[1])
    legs = inner[1][13]
    assert [(leg[0][0][0][0], leg[1][0][0][0], leg[6]) for leg in legs] == [
        ("BKK", "TPE", "2027-02-06"),
        ("TPE", "ICN", "2027-02-06"),
        ("ICN", "TPE", "2027-02-16"),
        ("TPE", "HKG", "2027-04-02"),
    ]
    assert segs[0][2] == date(2027, 2, 6)


def test_a_foreign_entry_in_the_list_does_not_hide_the_rows():
    rows = [_row(9000), "a header", None, [1, 2], _row(8000)]
    assert sorted(r[1][0][1] for r in itineraries([[rows]])) == [8000, 9000]


def test_midnight_times_come_with_a_missing_hour():
    from app.providers.google_http import _clock

    assert _clock([None, 35]) == (0, 35)
    assert _clock([20]) == (20, 0)
    assert _clock([23, 30]) == (23, 30)
    assert _clock([]) == (0, 0)


def test_a_kind_that_mostly_fails_is_paused():
    import time

    from app.providers.google_http import HttpFetcher

    f = HttpFetcher()
    for _ in range(12):
        f._record("mc", False)
    assert f.kind_pause["mc"] > time.time() + 500
    assert "ow" not in f.kind_pause
    for _ in range(12):
        f._record("ow", True)
    assert "ow" not in f.kind_pause

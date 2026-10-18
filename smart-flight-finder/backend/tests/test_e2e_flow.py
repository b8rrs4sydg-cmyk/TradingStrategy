"""End-to-end exercises that chain multiple endpoints the way a browser does.

These guard against drift between SearchResult, StrategyPlanOut, and the
PlanIn shape of /plans/ics and /plans/csv — a schema mismatch would quietly
break the frontend's export buttons.
"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


SEARCH_PAYLOAD = {
    "trip_type": "round_trip",
    "cabin": "economy",
    "adults": 1,
    "origins": ["TPE"],
    "destinations": ["NRT", "HND"],
    "strategies": ["standard", "reverse", "back_to_back_4leg"],
    "back_to_back_outer_stations": ["XMN"],
    "date_windows": [
        {"role": "outbound", "anchor_date": "2027-02-05", "flex_before": 1, "flex_after": 1},
        {"role": "return", "anchor_date": "2027-02-11", "flex_before": 1, "flex_after": 1},
    ],
}


def test_search_then_ics_then_csv_round_trip():
    r = client.post("/search", json=SEARCH_PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["plans"], "search should produce at least one plan on stub"

    # The frontend sends each StrategyPlanOut directly to /plans/ics as the body.
    first = body["plans"][0]
    r_ics = client.post("/plans/ics", json=first)
    assert r_ics.status_code == 200, r_ics.text
    assert r_ics.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VCALENDAR" in r_ics.text
    assert "END:VCALENDAR" in r_ics.text

    # And it batches selected plans into {plans: [...]} for /plans/csv.
    picks = body["plans"][:3]
    r_csv = client.post("/plans/csv", json={"plans": picks})
    assert r_csv.status_code == 200, r_csv.text
    assert r_csv.headers["content-type"].startswith("text/csv")
    header, *rows = r_csv.text.strip().splitlines()
    assert header.split(",")[:3] == ["plan_idx", "strategy", "total_cost"]
    assert len(rows) >= len(picks)   # one row per leg; ≥ ticket count


def test_metrics_updates_after_search():
    client.post("/search", json=SEARCH_PAYLOAD)
    text = client.get("/metrics").text
    assert "sff_search_requests_total" in text
    assert "sff_strategy_requested_total" in text
    # at least the strategies we requested appear
    assert 'strategy="standard"' in text


def test_search_with_candidate_windows_returns_labels_and_booking_links():
    payload = {
        **{k: v for k, v in SEARCH_PAYLOAD.items() if k != "date_windows"},
        "adults": 2,
        "strategies": ["standard"],
        "candidate_windows": [
            {"holiday_key": "lunar_ny", "depart": "2027-02-06", "return_date": "2027-02-14",
             "depart_flex": 0, "return_flex": 1},
            {"label": "聖誕", "depart": "2027-12-23", "return_date": "2027-12-27"},
        ],
    }
    r = client.post("/search", json=payload)
    assert r.status_code == 200, r.text
    plans = r.json()["plans"]
    assert {p["window_label"] for p in plans} == {"春節請 2 休 11", "聖誕"}
    links = plans[0]["tickets"][0]["booking_links"]
    assert [link["source"] for link in links] == ["trip_com", "google_flights", "skyscanner"]
    assert "quantity=2" in links[0]["url"]


def test_two_trip_search_returns_roles_trips_and_multi_city_links_through_csv():
    import csv
    import io

    payload = {
        **{k: v for k, v in SEARCH_PAYLOAD.items() if k != "date_windows"},
        "destinations": ["NRT", "LHR"],
        "strategies": ["reverse", "back_to_back_4leg"],
        "back_to_back_outer_stations": ["HKG", "ICN"],
        "candidate_windows": [
            {"holiday_key": "lunar_ny", "depart": "2027-02-05", "return_date": "2027-02-15"},
            {"holiday_key": "qingming", "depart": "2027-04-02", "return_date": "2027-04-11"},
            {"holiday_key": "xmas", "depart": "2027-12-23", "return_date": "2027-12-27"},
        ],
    }
    body = client.post("/search", json=payload).json()
    assert [n for n in body["notices"] if "LHR" not in n] == []
    four = next(p for p in body["plans"] if p["strategy"] == "back_to_back_4leg")
    assert four["ticket_roles"][1].startswith("外站四腿票") and len(four["trips"]) == 3
    trip_link = next(b for b in four["tickets"][1]["booking_links"] if b["source"] == "trip_com")
    assert "triptype=mt" in trip_link["url"]

    rows = list(csv.DictReader(io.StringIO(client.post("/plans/csv", json={"plans": [four]}).text)))
    assert any("triptype=mt" in r["trip_com_url"] for r in rows)


def test_single_slot_two_trip_strategies_return_notice():
    payload = {**SEARCH_PAYLOAD, "strategies": ["reverse"]}
    body = client.post("/search", json=payload).json()
    assert body["plans"] == [] and body["notices"]

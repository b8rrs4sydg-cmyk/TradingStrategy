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
    "back_to_back_outer_buffer_days": 2,
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

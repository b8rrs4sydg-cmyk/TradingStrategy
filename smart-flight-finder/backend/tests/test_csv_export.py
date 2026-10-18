from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _plan_payload(strategy: str, cost: int):
    return {
        "strategy": strategy,
        "total_cost": cost,
        "currency": "TWD",
        "tickets": [
            {
                "offer_id": f"{strategy}-A",
                "total_price": cost,
                "currency": "TWD",
                "legs": [
                    {
                        "origin": "TPE", "destination": "NRT",
                        "departure": "2027-02-05T09:00:00+00:00",
                        "arrival":   "2027-02-05T12:30:00+00:00",
                        "carrier": "BR", "flight_number": "BR188",
                    }
                ],
            }
        ],
    }


def test_csv_rejects_empty():
    r = client.post("/plans/csv", json={"plans": []})
    assert r.status_code == 400


def test_csv_returns_text_csv_with_rows_per_leg():
    r = client.post(
        "/plans/csv",
        json={"plans": [
            _plan_payload("standard", 15000),
            _plan_payload("back_to_back_4leg", 12800),
        ]},
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    lines = r.text.strip().splitlines()
    assert lines[0].split(",")[:3] == ["plan_idx", "strategy", "total_cost"]
    # Two plans × 1 ticket × 1 leg = 2 data rows + 1 header
    assert len(lines) == 3
    assert "standard" in r.text and "back_to_back_4leg" in r.text


def test_csv_includes_slot_label_and_trip_com_link():
    import csv
    import io

    plan = {**_plan_payload("standard", 15000), "window_label": "春節請 2 休 11"}
    r = client.post("/plans/csv", json={"plans": [plan]})
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert rows[0]["window_label"] == "春節請 2 休 11"
    assert rows[0]["trip_com_url"].startswith("https://tw.trip.com/flights/showfarefirst?")
    assert "dcity=tpe" in rows[0]["trip_com_url"] and "triptype=ow" in rows[0]["trip_com_url"]

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.models.enums import CabinClass, TicketStrategyType
from app.services.ics_export import render_plan_ics
from app.services.strategies.base import FlightLeg, StrategyPlan, TicketOffer

client = TestClient(app)


def test_render_includes_rfc5545_wrappers_and_vevents():
    dep = datetime(2027, 2, 5, 9, 0, tzinfo=UTC)
    leg1 = FlightLeg("TPE", "NRT", dep, dep + timedelta(hours=3), "BR", "BR188",
                     cabin=CabinClass.ECONOMY)
    leg2 = FlightLeg("NRT", "TPE",
                     dep + timedelta(days=6, hours=18),
                     dep + timedelta(days=6, hours=21, minutes=30),
                     "BR", "BR189",
                     cabin=CabinClass.ECONOMY)
    ticket = TicketOffer("rt-BR", (leg1, leg2), 15000)
    plan = StrategyPlan(
        strategy=TicketStrategyType.STANDARD,
        tickets=(ticket,),
        total_cost=15000,
        currency="TWD",
        total_travel_days=7,
        explain="直購：TPE→NRT",
    )
    ics = render_plan_ics(plan)
    assert ics.startswith("BEGIN:VCALENDAR\r\n")
    assert "END:VCALENDAR\r\n" in ics
    assert ics.count("BEGIN:VEVENT") == 2
    assert "DTSTART:20270205T090000Z" in ics
    assert "SUMMARY:" in ics
    # Line endings are CRLF
    assert "\r\n" in ics


def test_endpoint_returns_text_calendar_and_filename():
    payload = {
        "strategy": "standard",
        "tickets": [
            {
                "offer_id": "rt-BR",
                "total_price": 15000,
                "currency": "TWD",
                "legs": [
                    {
                        "origin": "TPE", "destination": "NRT",
                        "departure": "2027-02-05T09:00:00+00:00",
                        "arrival":   "2027-02-05T12:30:00+00:00",
                        "carrier": "BR", "flight_number": "BR188",
                    },
                    {
                        "origin": "NRT", "destination": "TPE",
                        "departure": "2027-02-11T18:00:00+00:00",
                        "arrival":   "2027-02-11T21:30:00+00:00",
                        "carrier": "BR", "flight_number": "BR189",
                    },
                ],
            }
        ],
        "total_cost": 15000,
    }
    r = client.post("/plans/ics", json=payload)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/calendar")
    assert "attachment" in r.headers["content-disposition"]
    assert "BEGIN:VCALENDAR" in r.text


def test_endpoint_rejects_empty_plan():
    r = client.post(
        "/plans/ics",
        json={"strategy": "standard", "tickets": [], "total_cost": 0},
    )
    assert r.status_code == 400

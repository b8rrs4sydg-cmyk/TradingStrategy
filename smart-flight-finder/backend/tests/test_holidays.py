from datetime import date

from fastapi.testclient import TestClient

from app.data import taiwan_holidays_2027 as tw27
from app.main import app
from app.models.enums import HolidayType

client = TestClient(app)


def test_list_holidays_falls_back_to_static_when_db_empty():
    """DB rows 為空時 router 應回傳靜態資料。"""
    resp = client.get("/holidays/2027")
    assert resp.status_code == 200
    rows = resp.json()
    assert len(rows) == len(tw27.HOLIDAYS)
    days = {date.fromisoformat(r["day"]) for r in rows}
    assert date(2027, 1, 1) in days          # 元旦
    assert date(2027, 10, 10) in days        # 國慶
    assert date(2027, 2, 7) in days          # 春節初一


def test_filter_by_kind():
    resp = client.get(f"/holidays/2027?kind={HolidayType.NATIONAL.value}")
    assert resp.status_code == 200
    for row in resp.json():
        assert row["kind"] == HolidayType.NATIONAL.value


def test_leave_strategies_present():
    resp = client.get("/holidays/2027/leave-strategies")
    assert resp.status_code == 200
    labels = {r["label_zh"] for r in resp.json()}
    assert "春節請 2 休 11" in labels
    assert "清明請 3 休 9" in labels


def test_leave_strategy_lookup_by_key():
    resp = client.get("/holidays/2027/lunar_ny")
    assert resp.status_code == 200
    assert resp.json()[0]["holiday_key"] == "lunar_ny"


def test_leave_strategy_lookup_unknown_404():
    resp = client.get("/holidays/2027/does_not_exist")
    assert resp.status_code == 404

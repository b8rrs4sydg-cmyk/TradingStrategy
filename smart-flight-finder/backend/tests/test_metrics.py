from fastapi.testclient import TestClient

from app.core.metrics import inc_counter, render_text, reset_for_tests, set_gauge
from app.main import app


def test_counters_render_prometheus_format():
    reset_for_tests()
    inc_counter("sff_test_requests_total", labels={"route": "search"})
    inc_counter("sff_test_requests_total", by=2, labels={"route": "search"})
    inc_counter("sff_test_requests_total", labels={"route": "metrics"})
    text = render_text()
    assert "# TYPE sff_test_requests_total counter" in text
    assert 'sff_test_requests_total{route="search"} 3' in text
    assert 'sff_test_requests_total{route="metrics"} 1' in text


def test_gauge_overwrites():
    reset_for_tests()
    set_gauge("sff_test_pool_size", 10)
    set_gauge("sff_test_pool_size", 7)
    text = render_text()
    assert "sff_test_pool_size 7" in text


def test_metrics_endpoint_increments_on_search():
    reset_for_tests()
    client = TestClient(app)
    payload = {
        "trip_type": "round_trip",
        "cabin": "economy",
        "adults": 1,
        "origins": ["TPE"],
        "destinations": ["NRT"],
        "strategies": ["standard"],
        "date_windows": [
            {"role": "outbound", "anchor_date": "2027-02-05", "flex_before": 1, "flex_after": 1},
            {"role": "return", "anchor_date": "2027-02-11", "flex_before": 1, "flex_after": 1},
        ],
    }
    r = client.post("/search", json=payload)
    assert r.status_code == 200

    m = client.get("/metrics")
    assert m.status_code == 200
    text = m.text
    assert "sff_search_requests_total" in text
    assert "sff_strategy_requested_total" in text

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_airport_catalog_for_checkboxes():
    from fastapi.testclient import TestClient

    from app.main import app

    body = TestClient(app).get("/airports").json()
    assert {a["code"] for a in body["origins"]} >= {"TPE", "KHH"}
    assert {"NRT", "LHR"} <= {a["code"] for a in body["destinations"]}
    assert "HKG" in {a["code"] for a in body["outstations"]}
    assert "LHR" not in {a["code"] for a in body["outstations"]}

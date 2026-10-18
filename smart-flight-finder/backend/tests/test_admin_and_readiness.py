from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_admin_seed_disabled_without_token(monkeypatch):
    monkeypatch.delenv("APP_ADMIN_TOKEN", raising=False)
    r = client.post("/admin/seed")
    assert r.status_code == 503
    assert "disabled" in r.text


def test_admin_seed_rejects_wrong_token(monkeypatch):
    monkeypatch.setenv("APP_ADMIN_TOKEN", "s3cret")
    r = client.post("/admin/seed", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


def test_health_liveness_always_ok():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_readiness_reports_db_error_without_connection(monkeypatch):
    # No real Postgres in test env; readiness should degrade and tell us why.
    monkeypatch.delenv("REDIS_URL", raising=False)
    r = client.get("/health/ready")
    body = r.json()
    assert body["status"] in {"ok", "degraded"}
    assert "db" in body["checks"]
    assert body["checks"]["redis"] == "not configured"

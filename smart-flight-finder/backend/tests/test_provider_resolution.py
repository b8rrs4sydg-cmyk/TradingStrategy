from __future__ import annotations

from unittest.mock import patch

import pytest

from app.providers.fare_db import FareDatabaseProvider
from app.services.search import NoFareSource, resolve_default_provider


@pytest.fixture(autouse=True)
def _no_fare_db(monkeypatch, tmp_path):
    for var in ("FARE_DB_PATH", "FARE_SNAPSHOT_PATH", "LIVE_FARES", "REDIS_URL",
                "AMADEUS_CLIENT_ID", "AMADEUS_CLIENT_SECRET", "SKYSCANNER_RAPIDAPI_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("app.services.search.DEFAULT_FARE_DB", tmp_path / "absent.json")


def test_without_any_real_source_there_is_no_fare_source():
    assert isinstance(resolve_default_provider(), NoFareSource)


def test_fare_db_from_env_or_repo_default(monkeypatch, tmp_path):
    db = tmp_path / "fares.json"
    db.write_text('{"fares": {}}')
    monkeypatch.setenv("FARE_DB_PATH", str(db))
    assert isinstance(resolve_default_provider(), FareDatabaseProvider)
    monkeypatch.delenv("FARE_DB_PATH")
    monkeypatch.setattr("app.services.search.DEFAULT_FARE_DB", db)
    p = resolve_default_provider()
    assert isinstance(p, FareDatabaseProvider) and p.live_budget == 0
    monkeypatch.setenv("LIVE_FARES", "1")
    monkeypatch.setenv("LIVE_FARE_BUDGET", "5")
    assert resolve_default_provider().live_budget == 5


def test_uses_amadeus_when_configured(monkeypatch):
    monkeypatch.setenv("AMADEUS_CLIENT_ID", "k")
    monkeypatch.setenv("AMADEUS_CLIENT_SECRET", "s")
    monkeypatch.setenv("AMADEUS_ENV", "test")

    class _FakeAmadeus:
        name = "amadeus"

        def __init__(self, env: str = "test") -> None:
            self.env = env

        def search(self, **kw):
            return []

    class _NoError(Exception):
        pass

    with patch.dict(
        "sys.modules",
        {"app.providers.amadeus": type("_M", (), {
            "AmadeusProvider": _FakeAmadeus,
            "AmadeusError": _NoError,
        })},
    ):
        p = resolve_default_provider()
    assert p.name == "amadeus"


def test_falls_back_on_amadeus_error(monkeypatch):
    monkeypatch.setenv("AMADEUS_CLIENT_ID", "k")
    monkeypatch.setenv("AMADEUS_CLIENT_SECRET", "s")

    class _Err(Exception):
        pass

    def _raise(env: str = "test"):
        raise _Err("bad env")

    with patch.dict(
        "sys.modules",
        {"app.providers.amadeus": type("_M", (), {
            "AmadeusProvider": _raise,
            "AmadeusError": _Err,
        })},
    ):
        p = resolve_default_provider()
    assert isinstance(p, NoFareSource)

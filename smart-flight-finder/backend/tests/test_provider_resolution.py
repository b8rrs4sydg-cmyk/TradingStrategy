from __future__ import annotations

from unittest.mock import patch

from app.providers.stub import StubFlightProvider
from app.services.search import resolve_default_provider


def test_falls_back_to_stub_without_credentials(monkeypatch):
    monkeypatch.delenv("AMADEUS_CLIENT_ID", raising=False)
    monkeypatch.delenv("AMADEUS_CLIENT_SECRET", raising=False)
    assert isinstance(resolve_default_provider(), StubFlightProvider)


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
    assert isinstance(p, StubFlightProvider)

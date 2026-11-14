"""Skyscanner adapter unit tests — mocks httpx; no network."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import httpx
import pytest

from app.providers.skyscanner import SkyscannerError, SkyscannerProvider, _parse_payload

SAMPLE = {
    "data": {
        "itineraries": [
            {
                "id": "it-1",
                "price": {"raw": 12345.67, "currency": "TWD", "formatted": "NT$12,346"},
                "legs": [
                    {
                        "segments": [
                            {
                                "origin": {"displayCode": "TPE"},
                                "destination": {"displayCode": "NRT"},
                                "departure": "2027-02-05T09:00:00",
                                "arrival": "2027-02-05T13:30:00",
                                "carriers": {"marketing": [{"alternateId": "BR"}]},
                                "flightNumber": "188",
                                "stopCount": 0,
                            }
                        ]
                    }
                ],
            }
        ]
    }
}


def test_parse_payload_single_itinerary():
    offers = _parse_payload(SAMPLE)
    assert len(offers) == 1
    o = offers[0]
    assert o.offer_id == "it-1"
    assert o.total_price == 12346
    assert o.currency == "TWD"
    assert o.legs[0].origin == "TPE"
    assert o.legs[0].destination == "NRT"
    assert o.legs[0].carrier == "BR"
    assert o.legs[0].flight_number == "BR188"


def test_requires_api_key(monkeypatch):
    monkeypatch.delenv("SKYSCANNER_RAPIDAPI_KEY", raising=False)
    with pytest.raises(SkyscannerError, match="not configured"):
        SkyscannerProvider()


class _FakeResponse:
    def __init__(self, status_code, json_data=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


class _FakeClient:
    def __init__(self, resp):
        self.resp = resp

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, *_a, **_kw):
        return self.resp


def test_search_happy_path():
    p = SkyscannerProvider(api_key="k")
    with patch.object(httpx, "Client", return_value=_FakeClient(_FakeResponse(200, SAMPLE))):
        offers = p.search(origin="TPE", destination="NRT", departure_date=date(2027, 2, 5))
    assert offers and offers[0].total_price == 12346


def test_search_bad_status_raises():
    p = SkyscannerProvider(api_key="k")
    with (
        patch.object(httpx, "Client", return_value=_FakeClient(_FakeResponse(429, text="rate limited"))),
        pytest.raises(SkyscannerError, match="429"),
    ):
        p.search(origin="TPE", destination="NRT", departure_date=date(2027, 2, 5))

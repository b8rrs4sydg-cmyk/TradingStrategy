"""Amadeus adapter unit tests — mocks the HTTP layer; no network."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import httpx
import pytest

from app.providers.amadeus import AmadeusError, AmadeusProvider, _parse_offer

SAMPLE_PAYLOAD = {
    "data": [
        {
            "id": "1",
            "price": {"grandTotal": "12345.67", "currency": "TWD"},
            "travelerPricings": [
                {
                    "fareDetailsBySegment": [
                        {"cabin": "ECONOMY", "class": "Y"}
                    ]
                }
            ],
            "itineraries": [
                {
                    "segments": [
                        {
                            "departure": {"iataCode": "TPE", "at": "2027-02-05T09:00:00"},
                            "arrival": {"iataCode": "NRT", "at": "2027-02-05T13:30:00"},
                            "carrierCode": "BR",
                            "number": "188",
                            "numberOfStops": 0,
                        }
                    ]
                }
            ],
        }
    ]
}


def test_parse_offer_minimum_fields():
    offer = _parse_offer(SAMPLE_PAYLOAD["data"][0])
    assert offer.offer_id == "1"
    assert offer.total_price == 12346
    assert offer.currency == "TWD"
    assert offer.fare_class == "Y"
    assert len(offer.legs) == 1
    leg = offer.legs[0]
    assert leg.origin == "TPE" and leg.destination == "NRT"
    assert leg.carrier == "BR"
    assert leg.flight_number == "BR188"


def test_requires_credentials():
    with pytest.raises(AmadeusError, match="not configured"):
        AmadeusProvider(client_id="", client_secret="")


def test_rejects_unknown_env():
    with pytest.raises(AmadeusError, match="Unknown Amadeus env"):
        AmadeusProvider(client_id="a", client_secret="b", env="staging")


class _FakeResponse:
    def __init__(self, status_code: int, json_data: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data or {}
        self.text = text

    def json(self):
        return self._json


class _FakeClient:
    def __init__(self, token_resp: _FakeResponse, search_resp: _FakeResponse) -> None:
        self.token_resp = token_resp
        self.search_resp = search_resp

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def post(self, *_a, **_kw):
        return self.token_resp

    def get(self, *_a, **_kw):
        return self.search_resp


def test_search_happy_path():
    provider = AmadeusProvider(client_id="k", client_secret="s", env="test")
    fake = _FakeClient(
        token_resp=_FakeResponse(200, {"access_token": "tok", "expires_in": 1800}),
        search_resp=_FakeResponse(200, SAMPLE_PAYLOAD),
    )
    with patch.object(httpx, "Client", return_value=fake):
        offers = provider.search(
            origin="TPE", destination="NRT", departure_date=date(2027, 2, 5)
        )
    assert len(offers) == 1
    assert offers[0].total_price == 12346


def test_search_oauth_failure():
    provider = AmadeusProvider(client_id="k", client_secret="s", env="test")
    fake = _FakeClient(
        token_resp=_FakeResponse(401, {}, text="invalid credentials"),
        search_resp=_FakeResponse(200, SAMPLE_PAYLOAD),
    )
    with (
        patch.object(httpx, "Client", return_value=fake),
        pytest.raises(AmadeusError, match="OAuth failed"),
    ):
        provider.search(
            origin="TPE", destination="NRT", departure_date=date(2027, 2, 5)
        )

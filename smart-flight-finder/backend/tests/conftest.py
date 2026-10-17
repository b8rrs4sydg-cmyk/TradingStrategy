"""API tests run against the deterministic FakeFareProvider.

The product resolves only real fare sources (the Google Flights fare
database); endpoints under test get the fake so their plans are stable.
Tests of the resolver itself import the real function directly.
"""

import pytest

from tests.fake_fares import FakeFareProvider


@pytest.fixture(autouse=True)
def _fake_fares(monkeypatch, request):
    if request.node.get_closest_marker("real_resolver"):
        return
    monkeypatch.setattr("app.services.search.resolve_default_provider", lambda: FakeFareProvider())


def pytest_configure(config):
    config.addinivalue_line("markers", "real_resolver: use the real provider resolver")

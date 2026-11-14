import pytest
from fastapi import HTTPException

from app.core.rate_limit import _LOCAL, RateLimit


@pytest.fixture(autouse=True)
def _reset_local_bucket():
    _LOCAL.clear()
    yield
    _LOCAL.clear()


def test_allows_up_to_limit():
    rl = RateLimit(limit=3, window_s=60)
    for i in range(3):
        count, _ = rl.check("ip-1")
        assert count == i + 1


def test_rejects_once_exceeded():
    rl = RateLimit(limit=2, window_s=60)
    rl.check("ip-2")
    rl.check("ip-2")
    with pytest.raises(HTTPException) as exc:
        rl.check("ip-2")
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers


def test_buckets_are_independent():
    rl = RateLimit(limit=1, window_s=60)
    rl.check("ip-A")   # OK
    rl.check("ip-B")   # OK — different bucket
    with pytest.raises(HTTPException):
        rl.check("ip-A")

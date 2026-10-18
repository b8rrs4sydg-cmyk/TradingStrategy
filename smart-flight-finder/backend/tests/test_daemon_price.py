"""The daemon prices over plain HTTP first and lets the browser decide whatever HTTP cannot read."""

import asyncio
import time
from collections import Counter, deque

from scripts import lookup_daemon
from scripts.lookup_daemon import Daemon


class FakeHttp:
    def __init__(self, entry):
        self.entry, self.calls, self.pause_until = entry, 0, 0.0

    async def fetch(self, key):
        self.calls += 1
        return self.entry


def make(http_entry, browser_entry):
    d = Daemon.__new__(Daemon)
    d.http = FakeHttp(http_entry)
    d.audit = deque(maxlen=40)
    d.path, d.browser_s, d.audits = Counter(), [], set()
    browser_calls = []

    async def browser_price(key, ctx, sem, seq):
        browser_calls.append(key)
        return browser_entry, False

    d.browser_price = browser_price
    return d, browser_calls


def run(d, key="ow|TPE|NRT|2027-04-03"):
    async def go():
        out = await d.price(key, None, None, 1)
        if d.audits:  # the background comparisons with the browser
            await asyncio.gather(*d.audits)
        return out

    return asyncio.run(go())


def test_http_price_is_used_without_the_browser(monkeypatch):
    monkeypatch.setattr(lookup_daemon, "HTTP_AUDIT", 0.0)
    d, calls = make({"price": 5000}, {"price": 5100})
    assert run(d) == ({"price": 5000}, False)
    assert calls == []


def test_browser_takes_over_when_http_could_not_read_a_price():
    d, calls = make(None, {"price": 5100})
    assert run(d) == ({"price": 5100}, False)
    assert len(calls) == 1 and d.path == {"browser": 1}


def test_audited_keys_answer_at_once_and_are_compared_in_the_background(monkeypatch):
    monkeypatch.setattr(lookup_daemon, "HTTP_AUDIT", 1.0)
    d, calls = make({"price": 5000}, {"price": 5100})

    async def go():
        out = await d.price("ow|TPE|NRT|2027-04-03", None, None, 1)
        assert calls == [] and len(d.audits) == 1  # the answer did not wait for the browser
        await asyncio.gather(*d.audits)
        return out

    assert asyncio.run(go()) == ({"price": 5000}, False)
    assert calls == ["ow|TPE|NRT|2027-04-03"] and list(d.audit) == [True]  # 2 % apart: agrees


def test_http_is_paused_when_it_keeps_disagreeing_with_the_browser(monkeypatch):
    monkeypatch.setattr(lookup_daemon, "HTTP_AUDIT", 1.0)
    d, _ = make({"price": 3000}, {"price": 5000})
    for _ in range(20):
        run(d)
    assert d.http.pause_until > time.time() + 1000
    assert len(d.audit) == 0


def test_http_price_stands_when_the_browser_cannot_confirm(monkeypatch):
    monkeypatch.setattr(lookup_daemon, "HTTP_AUDIT", 1.0)
    d, _ = make({"price": 5000}, None)
    assert run(d) == ({"price": 5000}, False)

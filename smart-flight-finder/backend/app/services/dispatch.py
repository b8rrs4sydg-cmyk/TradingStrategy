"""Which crawler asks for which fare key — the same answer on every page and every run.

Rendezvous (highest-random-weight) hashing: each key is scored against every crawler instance and the highest score
owns it. Nothing is shared or coordinated, yet

* a key always goes to the same crawler, so two pages (or a retry) never make two crawlers fetch it, and that crawler's
  memory cache and single-flight table see every repeat;
* when a crawler is down the keys it owned spread over the others, and the keys of the others do not move (round-robin
  by position would reshuffle all of them);
* adding crawlers moves only ``1/(n+1)`` of the keys, to the new one.

The page carries a JavaScript port (``ownerOf`` in ``public/index.html``); ``tests/test_dispatch.py`` runs both against
the same vectors, so the two cannot drift apart.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

_M32 = 0xFFFFFFFF


def score(instance: int, key: str) -> int:
    """FNV-1a over ``"<instance>|<key>"`` followed by murmur3's 32-bit finaliser (FNV alone clusters on similar keys)."""

    h = 0x811C9DC5
    for b in f"{instance}|{key}".encode():
        h = ((h ^ b) * 0x01000193) & _M32
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & _M32
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & _M32
    h ^= h >> 16
    return h


def owner(key: str, instances: Sequence[int]) -> int:
    """The instance (out of ``instances``, which must not be empty) that owns ``key``; ties go to the lower number."""

    return max(sorted(instances), key=lambda i: score(i, key))


def assign(keys: Iterable[str], instances: Sequence[int]) -> dict[int, list[str]]:
    """Keys per instance, duplicates removed, order kept."""

    out: dict[int, list[str]] = {i: [] for i in instances}
    for key in dict.fromkeys(keys):
        out[owner(key, instances)].append(key)
    return out

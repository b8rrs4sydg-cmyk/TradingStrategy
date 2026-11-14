"""Rendezvous dispatch: the same key → the same crawler, in Python and in the page's JavaScript."""

import json
import random
import re
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from app.services.dispatch import assign, owner, score

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "public" / "index.html"
KEYS = [
    f"ow|TPE|{d}|2027-0{m}-{day:02d}"
    for d in ("NRT", "KIX", "ICN", "BKK")
    for m in (1, 2, 3, 4)
    for day in range(1, 29)
]


def test_same_key_same_owner_and_duplicates_dropped():
    inst = [0, 1, 2, 3, 4, 5]
    assert owner(KEYS[7], inst) == owner(KEYS[7], list(reversed(inst)))
    out = assign([*KEYS, *KEYS], inst)
    assert sum(len(v) for v in out.values()) == len(KEYS)
    assert all(owner(k, inst) == i for i, ks in out.items() for k in ks)


def test_balanced():
    counts = Counter(owner(k, range(6)) for k in KEYS)
    assert set(counts) == set(range(6))
    assert max(counts.values()) < 1.5 * len(KEYS) / 6


def test_only_the_keys_of_a_lost_crawler_move():
    full = list(range(6))
    for lost in (0, 3):
        rest = [i for i in full if i != lost]
        for k in KEYS:
            before = owner(k, full)
            if before != lost:
                assert owner(k, rest) == before  # untouched keys stay where they were


def test_adding_a_crawler_moves_about_one_in_n_plus_one():
    moved = sum(owner(k, range(6)) != owner(k, range(7)) for k in KEYS)
    assert 0.05 * len(KEYS) < moved < 0.3 * len(KEYS)  # expected 1/7
    assert all(owner(k, range(7)) == 6 for k in KEYS if owner(k, range(6)) != owner(k, range(7)))


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_page_javascript_agrees_with_python():
    html = PAGE.read_text(encoding="utf-8")
    m = re.search(
        r"function hashScore.*?\n(?=// The lookup runs on every crawler)", html, re.DOTALL
    )
    assert m, "hashScore/ownerOf not found in the page"
    rnd = random.Random(1)
    cases = [(rnd.sample(range(12), rnd.randint(1, 8)), k) for k in KEYS[::7]]
    js = (
        m.group(0)
        + f"\nconst cases = {json.dumps(cases)};\n"
        + "console.log(JSON.stringify(cases.map(([ins, k]) => [ownerOf(k, ins), hashScore(ins[0], k)])));"
    )
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
    got = json.loads(out)
    assert got == [[owner(k, ins), score(ins[0], k)] for ins, k in cases]

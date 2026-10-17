"""On-demand fare lookup: fetch exactly the requested keys right now.

Triggered when the demo asks for fares the database lacks: Claude commits
``public/live-request.json`` (``{"rid": ..., "keys": [...]}``) and the
"Fare lookup" workflow runs this on a GitHub runner::

    python -m scripts.lookup_fares --request ../public/live-request.json \\
        --db ../public/fares-live.json

Progress is reported as a commit status (context ``fare-lookup``,
description ``done/total``) on the request commit, so whoever relays it to
the page can show a live progress bar. Results go to the live overlay
``fares-live.json`` (never the crawl's own file, so the two never collide).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from app.providers.fare_db import FareDatabase
from app.providers.google_flights import scrape

MAX_KEYS = 80
_DAY = r"\d{4}-\d{2}-\d{2}"
_KEY = re.compile(
    rf"^(ow\|[A-Z]{{3}}\|[A-Z]{{3}}\|{_DAY}|rt\|[A-Z]{{3}}\|[A-Z]{{3}}\|{_DAY}\|{_DAY}"
    rf"|mc(\|[A-Z]{{3}}-[A-Z]{{3}}-{_DAY}){{2,6}})$"
)


def valid_keys(keys: list) -> list[str]:
    """Well-formed keys only (the request comes from a web page), cheap ones first."""

    good = [k for k in dict.fromkeys(keys) if isinstance(k, str) and _KEY.match(k)]
    good.sort(key=lambda k: k.startswith("mc|"))
    return good[:MAX_KEYS]


class StatusReporter:
    """Commit status ``fare-lookup`` = progress, throttled to one call / 3 s."""

    def __init__(self, rid: str) -> None:
        self.rid = rid
        self.repo = os.getenv("GITHUB_REPOSITORY")
        self.sha = os.getenv("GITHUB_SHA")
        self.token = os.getenv("GITHUB_TOKEN")
        self.last = 0.0

    def post(self, state: str, description: str, *, force: bool = False) -> None:
        if not (self.repo and self.sha and self.token):
            print(f"[status] {state}: {description}", flush=True)
            return
        if not force and time.time() - self.last < 3:
            return
        self.last = time.time()
        body = json.dumps({"state": state, "context": "fare-lookup", "description": description[:140]})
        req = urllib.request.Request(
            f"https://api.github.com/repos/{self.repo}/statuses/{self.sha}",
            data=body.encode(),
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=10).close()
        except Exception as e:  # noqa: BLE001 — progress is best-effort
            print(f"status post failed: {e}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--request", type=Path, required=True)
    ap.add_argument("--db", type=Path, required=True)
    args = ap.parse_args()

    request = json.loads(args.request.read_text(encoding="utf-8"))
    rid = str(request.get("rid", ""))[:40]
    keys = valid_keys(request.get("keys", []))
    status = StatusReporter(rid)
    status.post("pending", f"0/{len(keys)} rid={rid}", force=True)

    def progress(done: int, total: int, missing: int) -> None:
        status.post("pending", f"{done}/{total} rid={rid} missing={missing}", force=done == total)

    fares, missing = asyncio.run(scrape(keys, concurrency=5, timeout_ms=40000, progress=progress))
    db = FareDatabase.load(args.db)
    db.merge(fares, today=datetime.now(UTC).date(), missing=[*db.missing, *missing])
    db.save(args.db)
    status.post("success", f"{len(fares)}/{len(keys)} found rid={rid} missing={len(missing)}", force=True)
    print(f"lookup {rid}: {len(fares)} found, {len(missing)} not on Google Flights")


if __name__ == "__main__":
    main()

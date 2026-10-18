"""Embed fares.json into the demo page's <script id="fare-snapshot"> tag.

The demo is a single self-contained HTML file (published as a Claude
Artifact, which cannot fetch external data), so the daily snapshot job
writes the fares straight into it::

    python -m scripts.embed_fare_snapshot ../public/fares.json ../public/index.html
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from app.providers.fare_db import FareDatabase

_TAG = re.compile(r'(<script id="fare-snapshot" type="application/json">)(.*?)(</script>)', re.DOTALL)


def embed(snapshot: dict, html: str) -> str:
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    out, n = _TAG.subn(lambda m: m.group(1) + payload + m.group(3), html, count=1)
    if n != 1:
        raise ValueError('no <script id="fare-snapshot"> tag in the page')
    return out


def main() -> None:
    fares_path, html_path = map(Path, sys.argv[1:3])
    snapshot = FareDatabase.load_with_live(fares_path).to_json()  # crawl + live lookups
    html_path.write_text(embed(snapshot, html_path.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"embedded {len(snapshot.get('fares', {}))} fares into {html_path}")


if __name__ == "__main__":
    main()

"""Split fares.json into documents for the demo artifact's shared db.

The published demo reads collection ``fares`` live (see ``subscribeLiveFares``
in public/index.html): a ``meta`` doc naming the chunks of one generation and
chunk docs ``c00``, ``c01`` … (each well under the 256 KiB document cap).
Claude writes them with the ArtifactData tool after each crawl::

    python -m scripts.export_fare_chunks ../public/fares.json /tmp/fare-chunks
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

MAX_BYTES = 180_000


def chunks(db: dict) -> tuple[dict, list[tuple[str, dict]]]:
    gen = db.get("generated_at") or ""
    docs: list[tuple[str, dict]] = []
    current: dict[str, dict] = {}
    size = 0
    for key, entry in sorted(db.get("fares", {}).items()):
        slim = {k: v for k, v in entry.items() if k != "hist"}  # history stays in the repo
        n = len(json.dumps({key: slim}, ensure_ascii=False).encode())
        if current and size + n > MAX_BYTES:
            docs.append((f"c{len(docs):02d}", {"gen": gen, "fares": current}))
            current, size = {}, 0
        current[key] = slim
        size += n
    if current:
        docs.append((f"c{len(docs):02d}", {"gen": gen, "fares": current}))
    meta = {
        "gen": gen,
        "generated_at": gen,
        "coverage": db.get("coverage", {}),
        "count": len(db.get("fares", {})),
        "chunks": [doc_id for doc_id, _ in docs],
    }
    return meta, docs


def main() -> None:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    meta, docs = chunks(json.loads(src.read_text(encoding="utf-8")))
    out.mkdir(parents=True, exist_ok=True)
    for doc_id, body in docs:
        (out / f"{doc_id}.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    print(f"{meta['count']} fares → {len(docs)} chunk docs + meta in {out}")


if __name__ == "__main__":
    main()

"""Relay a page's live-lookup request to the "Fare lookup" GitHub Action.

Run by Claude in the dev session when the demo sends ``FARE_LOOKUP <rid>``
(the request's keys come from the artifact db doc ``requests/<rid>``)::

    python -m scripts.relay_lookup dispatch <rid> <keys.json>   # → prints commit sha
    python -m scripts.relay_lookup watch <sha>                  # progress lines (Monitor)
    python -m scripts.relay_lookup export <out_dir>             # pull + db chunk docs

``watch`` prints one line per change — ``running 12/30``, then ``done …``
or ``failed …`` — so each line can be written back to ``requests/<rid>``.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from scripts.lookup_fares import valid_keys

REPO = "b8rrs4sydg-cmyk/TradingStrategy"
BRANCH = "claude/zealous-darwin-1kexus"
ROOT = Path(__file__).resolve().parents[3]
REQUEST = ROOT / "smart-flight-finder/public/live-request.json"


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True, text=True).stdout.strip()


def _api(path: str):
    with urllib.request.urlopen(f"https://api.github.com/repos/{REPO}/{path}", timeout=20) as r:
        return json.load(r)


def dispatch(rid: str, keys_file: str) -> None:
    keys = valid_keys(json.loads(Path(keys_file).read_text(encoding="utf-8")))
    if not keys:
        sys.exit("no valid keys")
    _git("pull", "-q", "--rebase", "origin", BRANCH)
    REQUEST.write_text(json.dumps({"rid": rid, "keys": keys}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    _git("add", str(REQUEST))
    _git("commit", "-q", "-m", f"data: live fare lookup request {rid} ({len(keys)} keys)")
    for _ in range(4):
        try:
            _git("push", "-q", "origin", f"HEAD:{BRANCH}")
            break
        except subprocess.CalledProcessError:
            _git("pull", "-q", "--rebase", "origin", BRANCH)
    print(_git("rev-parse", "HEAD"), len(keys))


def watch(sha: str, timeout_s: int = 1500) -> None:
    last, t0 = None, time.time()
    while time.time() - t0 < timeout_s:
        line = None
        try:
            statuses = [s for s in _api(f"commits/{sha}/statuses") if s["context"] == "fare-lookup"]
            runs = _api(f"actions/runs?head_sha={sha}").get("workflow_runs", [])
            run = next((r for r in runs if r["name"].startswith("Fare lookup")), None)
            if run and run["status"] == "completed" and run["conclusion"] != "success":
                line = f"failed run {run['conclusion']} {run['html_url']}"
            elif statuses:
                s = statuses[0]  # newest first
                desc = s["description"] or ""
                if s["state"] == "success":
                    line = f"crawled {desc}"
                    if run and run["status"] == "completed":
                        line = f"done {desc}"
                elif s["state"] in ("failure", "error"):
                    line = f"failed {desc}"
                else:
                    line = f"running {desc.split(' ')[0]}"
            elif run:
                line = f"started {run['status']}"
        except Exception as e:  # noqa: BLE001 — transient API errors: keep polling
            line = None
            print(f"poll error {e}", file=sys.stderr)
        if line and line != last:
            print(line, flush=True)
            last = line
        if line and line.startswith(("done", "failed")):
            return
        time.sleep(5)
    print("failed timeout", flush=True)


def export(out_dir: str) -> None:
    from scripts.export_fare_chunks import main as export_main

    _git("pull", "-q", "--rebase", "origin", BRANCH)
    sys.argv = ["export", str(ROOT / "smart-flight-finder/public/fares.json"), out_dir]
    export_main()


if __name__ == "__main__":
    cmd, *rest = sys.argv[1:]
    {"dispatch": dispatch, "watch": watch, "export": export}[cmd](*rest)

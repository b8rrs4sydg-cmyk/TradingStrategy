"""Always-on fare lookup daemon — the demo page asks, Google Flights answers.

Runs on a GitHub Actions runner (``fare-daemon.yml``, restarted every 5 h) with
one headless Chromium kept warm. It listens on a public pub/sub topic
(ntfy.sh) for lookup requests from the demo page and streams every fare back
the moment it is fetched, so the page can show the database hits at once and
fill in the rest live — no Claude session in the loop::

    page ──POST──▶ ntfy.sh/<REQ topic> ──▶ daemon ──▶ Google Flights
    page ◀──SSE─── ntfy.sh/<RES topic> ◀── fares, progress (batched)

Everything is also merged into ``public/fares-live.json`` and pushed to the
branch every ~90 s, so the database keeps what was fetched.

The topics are public-ish (they live in the repo), so every request is
validated (well-formed keys only, size-capped, rate-limited) before any
browser time is spent.

    python -m scripts.lookup_daemon run --req T1 --res T2 --db ../public/fares-live.json
    python -m scripts.lookup_daemon selftest --req T1 --res T2      # client side check
"""

from __future__ import annotations

import argparse
import asyncio
import heapq
import itertools
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from app.providers.fare_db import FareDatabase
from app.providers.google_flights import _fetch_one
from scripts.lookup_fares import MAX_KEYS, valid_keys

NTFY = os.getenv("NTFY_URL", "https://ntfy.sh")
MSG_BYTES = 3400            # ntfy turns messages over 4096 bytes into attachments
RATE_KEYS = 800             # accepted keys per window
RATE_WINDOW_S = 600
CACHE_TTL_S = 1800          # a key fetched in the last 30 min is answered from memory
FLUSH_EVERY_S = 6
HEARTBEAT_S = 20
PERSIST_EVERY_S = 90
CONCURRENCY = 5
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


RING: deque[str] = deque(maxlen=150)   # last log lines, committed with the fares (daemon-status.json)


def log(*args) -> None:
    """print() that cannot kill a task: Playwright's node driver leaves the shared
    stdout/stderr pipe non-blocking, so a print can raise BlockingIOError."""

    line = " ".join(str(a) for a in args)
    RING.append(f"{datetime.now(UTC):%H:%M:%S} {line}"[:300])
    try:
        print(*args, flush=True)
    except OSError:
        pass


# --- pure helpers (unit-tested) -----------------------------------------------
def parse_request(message: str) -> dict | None:
    """``{"rid","total","keys"}`` from one request message, else None."""

    try:
        data = json.loads(message)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("rid"), str):
        return None
    keys = valid_keys(data.get("keys") if isinstance(data.get("keys"), list) else [])
    if not keys:
        return None
    total = data.get("total")
    total = total if isinstance(total, int) and len(keys) <= total <= MAX_KEYS else len(keys)
    return {"rid": data["rid"][:40], "total": total, "keys": keys}


def compact(entry: dict) -> list:
    """Wire form of a fare entry: ``[price, dep, arr, stops, airline]`` (``[price]`` if no flight)."""

    first = entry.get("first")
    if not first:
        return [entry["price"]]
    return [entry["price"], first.get("dep"), first.get("arr"), first.get("stops", 0), first.get("airline")]


def split_results(rid: str, fares: dict, nf: list, done: int, total: int, *, final: bool) -> list[str]:
    """Result messages, each under :data:`MSG_BYTES`; the last one carries ``final``.

    ntfy.sh rate-limits anonymous publishers hard (and GitHub runners share IPs),
    so fares travel in the compact form (~35 per message) under the key ``f``.
    """

    fares = {k: compact(v) for k, v in fares.items()}

    def msg(f: dict, n: list, last: bool) -> str:
        return json.dumps(
            {"rid": rid, "done": done, "total": total, "f": f, "nf": n, "final": final and last},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    out: list[str] = []
    cur_f: dict = {}
    cur_n: list = []
    items = [("f", k, v) for k, v in fares.items()] + [("n", k, None) for k in nf]
    for kind, k, v in items:
        if kind == "f":
            cur_f[k] = v
        else:
            cur_n.append(k)
        if len(msg(cur_f, cur_n, False).encode()) > MSG_BYTES:
            if kind == "f":
                cur_f.pop(k)
            else:
                cur_n.pop()
            out.append(msg(cur_f, cur_n, False))
            cur_f, cur_n = ({k: v}, []) if kind == "f" else ({}, [k])
    out.append(msg(cur_f, cur_n, True))
    return out


class PriorityGate:
    """Counting semaphore that wakes the waiter with the smallest priority first
    (newest request first, one-ways/round trips before multi-city), so a fresh
    search is not stuck behind the leftovers of an abandoned one."""

    def __init__(self, n: int) -> None:
        self.free = n
        self.waiters: list[tuple[tuple, int, asyncio.Future]] = []
        self.counter = itertools.count()

    async def acquire(self, prio: tuple) -> None:
        if self.free > 0:
            self.free -= 1
            return
        fut = asyncio.get_running_loop().create_future()
        heapq.heappush(self.waiters, (prio, next(self.counter), fut))
        await fut

    def release(self) -> None:
        while self.waiters:
            _, _, fut = heapq.heappop(self.waiters)
            if not fut.done():
                fut.set_result(None)
                return
        self.free += 1


class RateLimiter:
    def __init__(self, limit: int = RATE_KEYS, window: float = RATE_WINDOW_S) -> None:
        self.limit, self.window = limit, window
        self.events: deque[tuple[float, int]] = deque()

    def allow(self, n: int, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        while self.events and self.events[0][0] < now - self.window:
            self.events.popleft()
        if sum(c for _, c in self.events) + n > self.limit:
            return False
        self.events.append((now, n))
        return True


# --- ntfy io (blocking, run in threads) ----------------------------------------
PUB = {"ok": 0, "r429": 0, "fail": 0}


def publish(topic: str, text: str, retries: int = 8) -> bool:
    for i in range(retries):
        try:
            req = urllib.request.Request(f"{NTFY}/{topic}", data=text.encode(), method="POST")
            urllib.request.urlopen(req, timeout=15).close()
            PUB["ok"] += 1
            return True
        except urllib.error.HTTPError as e:
            if e.code != 429:
                PUB["fail"] += 1
                log(f"publish http {e.code}")
                return False
            PUB["r429"] += 1
            if PUB["r429"] <= 5 or PUB["r429"] % 20 == 0:
                log(f"publish 429 #{PUB['r429']}: {e.read()[:120]!r}")
            wait = e.headers.get("Retry-After") if e.headers else None
            time.sleep(min(float(wait) if wait and wait.isdigit() else 5 * (i + 1), 30))   # back off, never drop
        except Exception as e:  # noqa: BLE001
            log(f"publish error {e}")
            time.sleep(2)
    PUB["fail"] += 1
    log("publish gave up")
    return False


def subscribe(topic: str, since: str, stop: threading.Event, handler) -> None:
    """Stream a topic, reconnecting forever; ``handler(message_dict)`` per message."""

    last = since
    while not stop.is_set():
        try:
            req = urllib.request.Request(f"{NTFY}/{topic}/json?since={last}")
            with urllib.request.urlopen(req, timeout=100) as r:
                for raw in r:
                    if stop.is_set():
                        return
                    try:
                        ev = json.loads(raw)
                    except ValueError:
                        continue
                    if ev.get("event") == "message":
                        last = str(ev.get("time", last))
                        handler(ev)
        except Exception as e:  # noqa: BLE001 — network blips: reconnect
            log(f"subscribe error {e}; reconnecting")
            time.sleep(3)


# --- daemon -------------------------------------------------------------------------
class Persister:
    """Merges fetched fares into the live overlay file and pushes it to git."""

    def __init__(self, path: Path) -> None:
        self.path = path.resolve()  # git -C <root> needs a path inside the repo
        self.db = FareDatabase.load(self.path)
        self.pending: dict[str, dict] = {}
        self.missing: list[str] = []
        self.lock = threading.Lock()
        self.dirty = False   # request activity since the last push → publish daemon-status.json

    def add(self, fares: dict, nf: list) -> None:
        with self.lock:
            self.pending.update(fares)
            self.missing += nf

    def flush(self, push: bool) -> int:
        with self.lock:
            fares, missing = self.pending, self.missing
            self.pending, self.missing = {}, []
        if not fares and not missing and not self.dirty:
            return 0
        self.dirty = False
        if fares or missing:
            self.db.merge(fares, today=datetime.now(UTC).date(), missing=[*self.db.missing, *missing])
            self.db.save(self.path)
        self.write_status({"fares_saved": len(self.db.fares)})
        if push and os.getenv("GITHUB_TOKEN"):
            self._git_push(len(fares))
        return len(fares)

    def write_status(self, extra: dict) -> None:
        status = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "publishes": dict(PUB),
            **extra,
            "log": list(RING),
        }
        try:
            (self.path.parent / "daemon-status.json").write_text(
                json.dumps(status, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
            )
        except OSError:
            pass

    def _git_push(self, n: int) -> None:
        root = Path(__file__).resolve().parents[3]
        branch = os.getenv("GITHUB_REF_NAME", "")
        for attempt in range(4):
            try:
                git = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True)
                git("add", str(self.path), str(self.path.parent / "daemon-status.json"))
                if subprocess.run(["git", "-C", str(root), "diff", "--cached", "--quiet"], check=False).returncode == 0:
                    return
                git("commit", "-q", "-m", f"data: live fare lookups (+{n})")
                git("pull", "-q", "--rebase", "origin", branch)
                git("push", "-q", "origin", f"HEAD:{branch}")
                return
            except subprocess.CalledProcessError as e:
                log(f"git retry {attempt}: {e.stderr[-200:] if e.stderr else e}")
                time.sleep(3)


class Daemon:
    def __init__(self, req: str, res: str, db_path: Path) -> None:
        self.req, self.res = req, res
        self.persist = Persister(db_path)
        self.limiter = RateLimiter()
        self.cache: dict[str, tuple[float, dict | None]] = {}
        self.requests: dict[str, dict] = {}     # rid → {total, done}
        self.seen: set[str] = set()
        self.queue: asyncio.Queue = asyncio.Queue()
        self.seq = 0

    async def run(self, duration: float) -> None:
        from playwright.async_api import async_playwright

        loop = asyncio.get_running_loop()
        stop = threading.Event()

        def on_message(ev: dict) -> None:
            if ev.get("id") in self.seen:
                return
            self.seen.add(ev.get("id"))
            loop.call_soon_threadsafe(self.queue.put_nowait, ev.get("message", ""))

        threading.Thread(target=subscribe, args=(self.req, str(int(time.time()) - 5), stop, on_message), daemon=True).start()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
            ctx = await browser.new_context(locale="en-US", user_agent=_UA)
            sem = PriorityGate(CONCURRENCY)
            log(f"daemon up: req={self.req} res={self.res} for {duration:.0f}s")
            deadline = time.time() + duration
            persist_task = asyncio.create_task(self._persist_loop())
            tasks: set[asyncio.Task] = set()
            while time.time() < deadline:
                try:
                    message = await asyncio.wait_for(self.queue.get(), timeout=5)
                except TimeoutError:
                    continue
                req = parse_request(message)
                log(f"request received: {'rid ' + req['rid'] + ' ' + str(len(req['keys'])) + ' keys' if req else 'REJECTED ' + message[:80]}")
                self.persist.dirty = True
                if req:
                    t = asyncio.create_task(self.handle(req, ctx, sem))
                    tasks.add(t)
                    t.add_done_callback(tasks.discard)
            stop.set()
            if tasks:
                await asyncio.wait(tasks, timeout=300)
            persist_task.cancel()
            await asyncio.to_thread(self.persist.flush, True)
            await browser.close()

    async def _persist_loop(self) -> None:
        while True:
            await asyncio.sleep(PERSIST_EVERY_S)
            await asyncio.to_thread(self.persist.flush, True)

    async def handle(self, req: dict, ctx, sem: PriorityGate) -> None:
        rid, keys = req["rid"], req["keys"]
        self.seq += 1
        seq = self.seq
        first_chunk = rid not in self.requests
        state = self.requests.setdefault(rid, {"total": req["total"], "done": 0})
        log(f"handle {rid}: first_chunk={first_chunk} total={state['total']}")
        fresh = [k for k in keys if (h := self.cache.get(k)) and time.time() - h[0] < CACHE_TTL_S]
        if not self.limiter.allow(len(keys) - len(fresh)):   # answers from memory cost nothing
            await asyncio.to_thread(publish, self.res, json.dumps({"rid": rid, "error": "rate_limited", "final": True}))
            return
        if first_chunk:
            await asyncio.to_thread(
                publish, self.res,
                json.dumps({"rid": rid, "done": 0, "total": state["total"], "f": {}, "nf": [], "final": False, "hello": True}),
            )
        out_f: dict[str, dict] = {}
        out_n: list[str] = []
        last_flush = time.time()

        async def one(key: str) -> None:
            hit = self.cache.get(key)
            failed = False
            if hit and time.time() - hit[0] < CACHE_TTL_S:
                entry = hit[1]
            else:
                await sem.acquire((-seq, key.startswith("mc|")))
                try:
                    entry = await _fetch_one(ctx, key, 40000)
                except Exception as e:  # noqa: BLE001
                    log(f"fetch failed {key}: {e}")
                    entry, failed = None, True
                finally:
                    sem.release()
                if not failed:   # a crash is not "no itinerary": do not cache or report it as unavailable
                    self.cache[key] = (time.time(), entry)
            state["done"] += 1
            if entry:
                out_f[key] = {**entry, "at": datetime.now(UTC).date().isoformat()}
            elif not failed:
                out_n.append(key)

        async def flusher(final: bool) -> None:
            nonlocal out_f, out_n
            f, n = out_f, out_n
            out_f, out_n = {}, []
            self.persist.add(f, n)
            finished = final and state["done"] >= state["total"]
            for text in split_results(rid, f, n, state["done"], state["total"], final=finished):
                await asyncio.to_thread(publish, self.res, text)

        pending = [asyncio.create_task(one(k)) for k in keys]
        t0 = time.time()
        last_sent = time.time()
        while not all(t.done() for t in pending):
            await asyncio.wait(pending, timeout=FLUSH_EVERY_S, return_when=asyncio.FIRST_COMPLETED)
            now = time.time()
            if (out_f or out_n) and now - last_flush >= FLUSH_EVERY_S:
                await flusher(False)
                last_flush = last_sent = time.time()
            elif now - last_sent >= HEARTBEAT_S:   # keeps the page from deciding we died
                await flusher(False)
                last_sent = time.time()
        await flusher(True)
        log(f"request {rid}: {len(keys)} keys done in {time.time() - t0:.0f}s; ntfy publishes {PUB}")


# --- self test (client side) -------------------------------------------------------------
def selftest(req: str, res: str, keys: list[str], timeout: float) -> int:
    """Post a request exactly like the page does and wait for the streamed answer."""

    rid = "selftest" + str(int(time.time()))
    got: dict[str, dict] = {}
    final = threading.Event()

    def on_result(ev: dict) -> None:
        try:
            m = json.loads(ev.get("message", ""))
        except ValueError:
            return
        if m.get("rid") != rid:
            return
        got.update(m.get("f", {}))
        log(f"  {m.get('done')}/{m.get('total')} fares={len(got)} nf={len(m.get('nf', []))} hello={m.get('hello', False)}")
        if m.get("final") or m.get("error"):
            final.set()

    stop = threading.Event()
    threading.Thread(target=subscribe, args=(res, "10s", stop, on_result), daemon=True).start()
    time.sleep(3)
    t0 = time.time()
    ok = publish(req, json.dumps({"rid": rid, "total": len(keys), "keys": keys}))
    log(f"selftest published={ok}")
    final.wait(timeout)
    stop.set()
    log(f"selftest finished={final.is_set()} fares={len(got)} in {time.time() - t0:.1f}s")
    return 0 if final.is_set() and got else 1


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--req", required=True)
    r.add_argument("--res", required=True)
    r.add_argument("--db", type=Path, required=True)
    r.add_argument("--duration", type=float, default=5.2 * 3600)
    s = sub.add_parser("selftest")
    s.add_argument("--req", required=True)
    s.add_argument("--res", required=True)
    s.add_argument("--keys", default="ow|TPE|HKG|2027-02-03,rt|TPE|NRT|2027-02-05|2027-02-15")
    s.add_argument("--timeout", type=float, default=180)
    s.add_argument("--count", type=int, default=0, help="instead of --keys: this many one-way queries")
    args = ap.parse_args()
    if args.cmd == "run":
        asyncio.run(Daemon(args.req, args.res, args.db).run(args.duration))
    else:
        keys = args.keys.split(",")
        if args.count:
            from datetime import timedelta

            origins = ["TPE", "HKG", "NRT", "ICN"]
            base = datetime.now(UTC).date() + timedelta(days=120)
            keys = [
                f"ow|TPE|{origins[1 + i % 3]}|{base + timedelta(days=i // 3)}" for i in range(args.count)
            ]
        sys.exit(selftest(args.req, args.res, keys, args.timeout))


if __name__ == "__main__":
    main()

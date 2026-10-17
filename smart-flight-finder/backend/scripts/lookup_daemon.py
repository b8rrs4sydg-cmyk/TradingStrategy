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
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from app.providers.fare_db import FareDatabase
from app.providers.google_flights import _fetch_one
from scripts.lookup_fares import MAX_KEYS, valid_keys

NTFY = os.getenv("NTFY_URL", "https://ntfy.sh")
MSG_BYTES = 3400  # ntfy turns messages over 4096 bytes into attachments
RATE_KEYS = 2500  # accepted keys per window
RATE_WINDOW_S = 600
CACHE_TTL_S = 1800  # a key fetched in the last 30 min is answered from memory
FLUSH_EVERY_S = 6
HEARTBEAT_S = 20
PERSIST_EVERY_S = 90
CONCURRENCY = 8
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36"
)


RING: deque[str] = deque(
    maxlen=150
)  # last log lines, committed with the fares (daemon-status.json)


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
    return [
        entry["price"],
        first.get("dep"),
        first.get("arr"),
        first.get("stops", 0),
        first.get("airline"),
    ]


def split_results(
    rid: str, fares: dict, nf: list, done: int, total: int, *, final: bool
) -> list[str]:
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
            time.sleep(
                min(float(wait) if wait and wait.isdigit() else 5 * (i + 1), 30)
            )  # back off, never drop
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
        self.dirty = False  # request activity since the last push → publish daemon-status.json

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
            self.db.merge(
                fares, today=datetime.now(UTC).date(), missing=[*self.db.missing, *missing]
            )
            self.db.save(self.path)
        self.write_status({"fares_saved": len(self.db.fares)})
        if push and os.getenv("GITHUB_TOKEN"):
            self._git_push(len(fares))
        return len(fares)

    def announce(self, urls: list[str]) -> None:
        """Tell pages where to reach this daemon (daemon.json: independent tunnels, the page tries each)."""

        (self.path.parent / "daemon.json").write_text(
            json.dumps(
                {
                    "url": urls[0] if urls else None,
                    "urls": urls,
                    "at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
            )
            + "\n",
            encoding="utf-8",
        )
        if os.getenv("GITHUB_TOKEN"):
            self._git_push(0)

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
                git = lambda *a: subprocess.run(
                    ["git", "-C", str(root), *a], check=True, capture_output=True
                )
                git(
                    "add",
                    str(self.path),
                    str(self.path.parent / "daemon-status.json"),
                    str(self.path.parent / "daemon.json"),
                )
                if (
                    subprocess.run(
                        ["git", "-C", str(root), "diff", "--cached", "--quiet"], check=False
                    ).returncode
                    == 0
                ):
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
        self.requests: dict[str, dict] = {}  # rid → {total, done}
        self.seen: set[str] = set()
        self.queue: asyncio.Queue = asyncio.Queue()
        self.buffers: dict[str, dict] = {}  # rid -> {msgs, t}: what SSE subscribers read
        self.tunnel_url: str | None = None
        self.tunnel_urls: list[str] = []
        self.seq = 0

    async def run(self, duration: float) -> None:
        from playwright.async_api import async_playwright

        loop = asyncio.get_running_loop()
        stop = threading.Event()

        def on_message(ev: dict) -> None:
            if ev.get("id") in self.seen:
                return
            self.seen.add(ev.get("id"))
            loop.call_soon_threadsafe(self.queue.put_nowait, ("ntfy", ev.get("message", "")))

        threading.Thread(
            target=subscribe,
            args=(self.req, str(int(time.time()) - 5), stop, on_message),
            daemon=True,
        ).start()
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                args=["--disable-blink-features=AutomationControlled"]
            )
            ctx = await browser.new_context(locale="en-US", user_agent=_UA)
            sem = PriorityGate(CONCURRENCY)
            if os.getenv("DAEMON_HTTP", "1") == "1":
                await start_http(self)
                found = await asyncio.gather(
                    start_tunnel(), start_tunnel_ssh()
                )  # two independent providers
                self.tunnel_urls = [u for u in found if u]
                self.tunnel_url = self.tunnel_urls[0] if self.tunnel_urls else None
                self.persist.announce(self.tunnel_urls)
                log(f"http front door: {self.tunnel_urls}")
            log(f"daemon up: req={self.req} res={self.res} for {duration:.0f}s")
            deadline = time.time() + duration
            persist_task = asyncio.create_task(self._persist_loop())
            publisher_task = asyncio.create_task(self.publisher())
            tasks: set[asyncio.Task] = set()
            while time.time() < deadline:
                try:
                    via, message = await asyncio.wait_for(self.queue.get(), timeout=5)
                except TimeoutError:
                    continue
                req = parse_request(message)
                if req:
                    req["via"] = via
                log(
                    f"request received: {'rid ' + req['rid'] + ' ' + str(len(req['keys'])) + ' keys' if req else 'REJECTED ' + message[:80]}"
                )
                self.persist.dirty = True
                if req:
                    t = asyncio.create_task(self.handle(req, ctx, sem))
                    tasks.add(t)
                    t.add_done_callback(tasks.discard)
            stop.set()
            if tasks:
                await asyncio.wait(tasks, timeout=300)
            persist_task.cancel()
            publisher_task.cancel()
            await asyncio.to_thread(self.persist.flush, True)
            await browser.close()

    async def _persist_loop(self) -> None:
        while True:
            await asyncio.sleep(PERSIST_EVERY_S)
            await asyncio.to_thread(self.persist.flush, True)

    async def handle(self, req: dict, ctx, sem: PriorityGate) -> None:
        """Fetch one chunk of a request; results are buffered per request and sent by :meth:`publisher`."""

        rid, keys = req["rid"], req["keys"]
        self.seq += 1
        seq = self.seq
        first_chunk = rid not in self.requests
        state = self.requests.setdefault(
            rid,
            {
                "total": req["total"],
                "done": 0,
                "f": {},
                "nf": [],
                "active": 0,
                "last_sent": 0.0,
                "last_activity": time.time(),
                "final_sent": False,
                "via": req.get("via", "ntfy"),
            },
        )
        log(f"handle {rid}: first_chunk={first_chunk} total={state['total']}")
        fresh = [k for k in keys if (h := self.cache.get(k)) and time.time() - h[0] < CACHE_TTL_S]
        if not self.limiter.allow(len(keys) - len(fresh)):  # answers from memory cost nothing
            await self.send(
                rid,
                json.dumps({"rid": rid, "error": "rate_limited", "final": True}),
                req.get("via", "ntfy"),
            )
            return
        state["active"] += 1
        if first_chunk:  # lets the page see the crawler is alive at once
            state["last_sent"] = time.time()
            await self.send(
                rid,
                json.dumps(
                    {
                        "rid": rid,
                        "done": 0,
                        "total": state["total"],
                        "f": {},
                        "nf": [],
                        "final": False,
                        "hello": True,
                    }
                ),
                req.get("via", "ntfy"),
            )

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
                if (
                    not failed
                ):  # a crash is not "no itinerary": do not cache or report it as unavailable
                    self.cache[key] = (time.time(), entry)
            state["done"] += 1
            state["last_activity"] = time.time()
            if entry:
                state["f"][key] = {**entry, "at": datetime.now(UTC).date().isoformat()}
            elif not failed:
                state["nf"].append(key)

        t0 = time.time()
        try:
            await asyncio.gather(*(one(k) for k in keys))
        finally:
            state["active"] -= 1
            state["last_activity"] = time.time()
        log(
            f"request {rid}: chunk of {len(keys)} keys done in {time.time() - t0:.0f}s; ntfy publishes {PUB}"
        )

    async def send(self, rid: str, text: str, via: str) -> None:
        """Every message goes to the SSE buffer; requests that arrived over ntfy are also answered over ntfy."""

        buf = self.buffers.setdefault(rid, {"msgs": [], "t": time.time()})
        buf["msgs"].append(text)
        buf["t"] = time.time()
        if via == "ntfy":
            await asyncio.to_thread(publish, self.res, text)

    async def publisher(self) -> None:
        """One sender for every request: results are coalesced per request and sent at most every
        FLUSH_EVERY_S (a heartbeat every HEARTBEAT_S) — ntfy.sh rate-limits anonymous publishers."""

        while True:
            await asyncio.sleep(2)
            now = time.time()
            for old in [r for r, b in self.buffers.items() if now - b["t"] > 1200]:
                del self.buffers[old]
            for rid, st in list(self.requests.items()):
                if st["final_sent"]:
                    if now - st["last_activity"] > 900:
                        del self.requests[rid]
                    continue
                quiet = (
                    st["active"] == 0 and now - st["last_activity"] > 60
                )  # missing chunk: stop waiting
                finished = st["active"] == 0 and (st["done"] >= st["total"] or quiet)
                has_data = bool(st["f"] or st["nf"])
                due = has_data and now - st["last_sent"] >= FLUSH_EVERY_S
                beat = now - st["last_sent"] >= HEARTBEAT_S
                if not (finished or due or beat):
                    continue
                f, n = st["f"], st["nf"]
                st["f"], st["nf"] = {}, []
                self.persist.add(f, n)
                for text in split_results(rid, f, n, st["done"], st["total"], final=finished):
                    await self.send(rid, text, st["via"])
                    await asyncio.sleep(0.2)
                st["last_sent"] = time.time()
                if finished:
                    st["final_sent"] = True
                    log(
                        f"request {rid}: final sent ({st['done']}/{st['total']}); ntfy publishes {PUB}"
                    )


# --- HTTP front door: the page talks to the daemon directly (through a Cloudflare quick tunnel) --------
def make_app(daemon: Daemon):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"]
    )

    @app.get("/health")
    async def health() -> dict:
        return {
            "ok": True,
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "requests": len(daemon.requests),
        }

    @app.post("/lookup")
    async def lookup(request: Request):
        body = await request.body()
        if len(body) > 64_000:
            return JSONResponse({"error": "too_large"}, status_code=413)
        text = body.decode("utf-8", "replace")
        if parse_request(text) is None:
            return JSONResponse({"error": "bad_request"}, status_code=400)
        daemon.queue.put_nowait(("http", text))
        return {"ok": True}

    @app.get("/poll/{rid}")
    async def poll(rid: str, i: int = 0):
        """Long poll (Cloudflare quick tunnels do not carry Server-Sent Events): messages from index ``i`` on."""

        end = time.time() + 20
        while True:
            buf = daemon.buffers.get(rid[:40])
            msgs = buf["msgs"] if buf else []
            if i < len(msgs) or time.time() >= end:
                return {
                    "msgs": msgs[i : i + 50],
                    "next": min(len(msgs), i + 50) if i < len(msgs) else i,
                }
            await asyncio.sleep(0.25)

    @app.get("/events/{rid}")
    async def events(rid: str):
        async def stream():
            i, last, ping = 0, time.time(), time.time()
            yield (
                ": open" + " " * 2048 + "\n\n"
            )  # headers + first bytes at once: the page posts its request only after the stream opens
            while time.time() - last < 900:
                buf = daemon.buffers.get(rid[:40])
                if buf and i < len(buf["msgs"]):
                    text = buf["msgs"][i]
                    i += 1
                    last = time.time()
                    yield f"data: {text}\n\n"
                    if '"final":true' in text:
                        return
                else:
                    await asyncio.sleep(0.25)
                    if time.time() - ping > 10:
                        ping = time.time()
                        yield ": ping\n\n"

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


async def start_http(daemon: Daemon, port: int = 8787) -> None:
    import uvicorn

    server = uvicorn.Server(
        uvicorn.Config(make_app(daemon), host="127.0.0.1", port=port, log_level="warning")
    )
    server.install_signal_handlers = lambda: None  # type: ignore[method-assign]
    asyncio.create_task(server.serve())
    for _ in range(40):
        await asyncio.sleep(0.25)
        if server.started:
            return


async def start_tunnel(port: int = 8787) -> str | None:
    """Cloudflare quick tunnel (no account): returns its https URL, or None."""

    exe = shutil.which("cloudflared")
    if not exe:
        log("cloudflared not installed — ntfy only")
        return None
    proc = await asyncio.create_subprocess_exec(
        exe,
        "tunnel",
        "--url",
        f"http://127.0.0.1:{port}",
        "--no-autoupdate",
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    found: asyncio.Future = asyncio.get_running_loop().create_future()

    async def drain() -> None:
        assert proc.stderr
        async for raw in proc.stderr:
            m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", raw.decode("utf-8", "replace"))
            if m and not found.done():
                found.set_result(m.group(0))

    asyncio.create_task(drain())
    try:
        return await asyncio.wait_for(found, timeout=60)
    except TimeoutError:
        log("tunnel did not come up in 60 s")
        return None


async def start_tunnel_ssh(port: int = 8787) -> str | None:
    """Second, independent tunnel (localhost.run over ssh, no account): returns its https URL, or None."""

    exe = shutil.which("ssh")
    if not exe:
        return None
    proc = await asyncio.create_subprocess_exec(
        exe,
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "ServerAliveInterval=30",
        "-o",
        "ExitOnForwardFailure=yes",
        "-R",
        f"80:127.0.0.1:{port}",
        "nokey@localhost.run",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    found: asyncio.Future = asyncio.get_running_loop().create_future()

    async def drain() -> None:
        assert proc.stdout
        async for raw in proc.stdout:
            m = re.search(r"https://[a-z0-9-]+\.lhr\.life", raw.decode("utf-8", "replace"))
            if m and not found.done():
                found.set_result(m.group(0))

    asyncio.create_task(drain())
    try:
        return await asyncio.wait_for(found, timeout=60)
    except TimeoutError:
        log("ssh tunnel did not come up in 60 s")
        return None


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
        log(
            f"  {m.get('done')}/{m.get('total')} fares={len(got)} nf={len(m.get('nf', []))} hello={m.get('hello', False)}"
        )
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


def selftest_http(daemon_json: Path, keys: list[str], timeout: float) -> int:
    """Same as :func:`selftest`, but through the public tunnel URL the daemon announced."""

    url = None
    for _ in range(60):
        try:
            url = json.loads(daemon_json.read_text(encoding="utf-8")).get("url")
        except (OSError, ValueError):
            url = None
        if url:
            break
        time.sleep(3)
    if not url:
        log("selftest-http: no tunnel URL announced")
        return 1
    rid = "httptest" + str(int(time.time()))
    t0 = time.time()
    for attempt in range(10):  # a fresh quick tunnel needs a moment before it resolves
        try:
            urllib.request.urlopen(f"{url}/health", timeout=8).read()
            break
        except Exception as e:  # noqa: BLE001
            log(f"selftest-http: tunnel not ready ({e})")
            time.sleep(4)
    body = json.dumps({"rid": rid, "total": len(keys), "keys": keys}).encode()
    urllib.request.urlopen(
        urllib.request.Request(f"{url}/lookup", data=body, method="POST"), timeout=15
    ).read()
    got, final, nxt = 0, False, 0
    while not final and time.time() - t0 < timeout:  # the same long poll the page uses
        with urllib.request.urlopen(f"{url}/poll/{rid}?i={nxt}", timeout=30) as resp:
            j = json.loads(resp.read())
        nxt = j["next"]
        for text in j["msgs"]:
            m = json.loads(text)
            got += len(m.get("f", {}))
            log(f"  http {m.get('done')}/{m.get('total')} fares={got}")
            if m.get("final") or m.get("error"):
                final = True
    log(f"selftest-http finished={final} fares={got} in {time.time() - t0:.1f}s via {url}")
    return 0 if final and got else 1


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
    s.add_argument(
        "--count", type=int, default=0, help="instead of --keys: this many one-way queries"
    )
    h = sub.add_parser("selftest-http")
    h.add_argument("--daemon-json", type=Path, required=True)
    h.add_argument("--count", type=int, default=20)
    h.add_argument("--timeout", type=float, default=240)
    args = ap.parse_args()
    if args.cmd == "selftest-http":
        from datetime import timedelta

        base = datetime.now(UTC).date() + timedelta(days=130)
        keys = [
            f"ow|TPE|{('HKG', 'ICN', 'BKK')[i % 3]}|{base + timedelta(days=i // 3)}"
            for i in range(args.count)
        ]
        sys.exit(selftest_http(args.daemon_json, keys, args.timeout))
    if args.cmd == "run":
        asyncio.run(Daemon(args.req, args.res, args.db).run(args.duration))
    else:
        keys = args.keys.split(",")
        if args.count:
            from datetime import timedelta

            origins = ["TPE", "HKG", "NRT", "ICN"]
            base = datetime.now(UTC).date() + timedelta(days=120)
            keys = [
                f"ow|TPE|{origins[1 + i % 3]}|{base + timedelta(days=i // 3)}"
                for i in range(args.count)
            ]
        sys.exit(selftest(args.req, args.res, keys, args.timeout))


if __name__ == "__main__":
    main()

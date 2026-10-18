# Smart Flight Finder — Architecture Notes

Context for future Claude Code sessions picking up this project. Keep this file
short; put long-form product content in `docs/spec.md` and `docs/roadmap.md`.

## High-level

Monorepo with two independently deployable services:

```
backend/   FastAPI + SQLAlchemy 2.0 + Alembic + Redis-ready
frontend/  Next.js 14 (App Router) + Tailwind
deploy/    Render + Vercel configs
```

Dev workflow: `docker compose up --build` runs the four services (Postgres,
Redis, api, web). Backend hot-reloads via `uvicorn --reload`; frontend via
`next dev`.

## Backend layering (strict, bottom → top)

```
app/models/            SQLAlchemy ORM — persistence shape only
app/schemas/           Pydantic I/O — never imports ORM, only `enums`
app/data/              Static seed data (2027 TW holidays)
app/providers/         FlightOfferProvider protocol + Google Flights fare DB, Amadeus, Cache
app/services/
  mct.py               Minimum connection time policy
  date_matrix.py       DateWindow → candidate dates, with pruning
  strategies/          One class per TicketStrategyType
    base.py            FlightLeg / TicketOffer / StrategyPlan dataclasses
    standard.py        Round-trip + multi-city (branches on trip_type)
    reverse.py         A↔B vs B↔A arbitrage
    back_to_back.py    外站四段票 — the key differentiator
    open_jaw.py        不同進出點 (A ≠ B)
  scoring.py           Min-max normalized weighted scoring
  search.py            Orchestrator; resolves provider from env
  seed_holidays.py     Idempotent upsert of 2027 data
app/routers/           Thin FastAPI endpoints — never business logic
```

Rules of thumb:

- **No cycle** between `providers/` and `services/strategies/base`. The
  Protocol in `providers/base.py` uses `TYPE_CHECKING` for the `TicketOffer`
  return annotation.
- A new strategy = a new file under `app/services/strategies/` exporting a
  class with `.strategy` and `.plan(...)`, plus a dispatch arm in
  `SearchService._run_strategy`.
- A new data source = a new class under `app/providers/` implementing the
  `FlightOfferProvider` Protocol (`search` + `search_multi_city`; return `[]`
  if the API can't quote multi-city). `CachingProvider` wraps it per request.

## Date matrix pruning (`date_matrix.py`)

- `expand_window` yields the ± flex candidates (filterable to weekends).
- `iter_date_combos` is the single source of truth for pruning the cartesian
  product:
  - `round_trip`: `min_days_abroad ≤ return − outbound ≤ max_days_abroad?`
  - `multi_city`: strict chronological order across segments.
- Planners either consume `iter_date_combos` or pair dates manually (standard
  does the latter for simpler round-trip code).

## Multi-trip strategies — 反向票＋倒買法 (2 trips) and 外站四腿票 (3 trips)

Both only pay off when ONE purchase covers several trips, so `SearchService`
runs 反向票＋倒買法 over ordered pairs of non-overlapping `candidate_windows`
(`_slot_pairs`) and 四腿票 over ordered triples (`_slot_triples`). With too few
slots they return nothing plus a `notices` entry. Shared helpers live in
`strategies/two_trip.py` (`TripSlot`, `quote` → round trip if the two segments
mirror, else `search_multi_city`, `best_pair` constrained cheapest combination).

```
反向票＋倒買法 (reverse.py), home H; each trip has its own in/out city in ONE
country (大阪進東京出); only JP/TH/KR (DAOMAI_COUNTRIES, others → notice):
  包覆票  H→A_in (A start) + B_out→H (B end)   ← always exactly two tickets
  反向票  A_out→H (A end)  + H→B_in (B start)  ← foreign-origin, cheap in TW 連假
外站四腿票 (back_to_back.py), one ticket X→TPE→D→TPE→Y over THREE slots P<Q<R,
X, D, Y in three different countries:
  旅程1 (P): 單買初段 TPE→X · stay in X, any length · leg1 X→TPE (inside P's window)
  旅程2 (Q): leg2 TPE→D · leg3 D→TPE        (leg 1 is NOT glued to leg 2)
  旅程3 (R): leg4 TPE→Y · 單買最後一段 Y→TPE (or next 四腿票 leg1 = 循環)
```

Plans that beat ordinary round trips for both trips are kept; if none does,
the closest one is returned flagged `no_saving` (MEDIUM, "實價不划算，僅供比較")
so the real comparison stays visible. Plans carry `ticket_roles` + `trips`, and scoring divides price / flight time /
PTO efficiency by `trip_count` so they compare fairly with single trips.
Tickets carry `searched_segments`; `booking_links` turns every ticket priced
over ≥ 2 segments (包覆票 / 反向票 / 四腿票, mirrored pairs included) into
multi-city links; plain round trips keep round-trip links. Link
formats were checked in a real browser — see the module docstring:
Google `tfs` (trip 1/2/3) is exact; Trip.com (tw.trip.com) needs city codes
+ airport params, and multi-city uses its native `multdcity{i}`/
`multacity{i}`/`multddate{i}` URL (what its own search button emits);
Skyscanner gets no multi-city link (bot wall, unverifiable). The demo
(`public/index.html`) mirrors all of this in JS — keep both in sync.

## Fares — real Google Flights prices only

There is NO simulated price source in the product (the old stub lives on
only as `tests/fake_fares.py`, a deterministic test double). Amadeus
Self-Service shut down 2026-07-17; every price comes from Google Flights:

- `providers/google_flights.py` — query keys (`ow|O|D|day`, `rt|O|D|dep|ret`,
  `mc|O-D-day|…`, same strings in the demo JS), the `tfs` search URL
  (`hl=en&gl=TW&curr=TWD`; without `gl=TW` round trips show no results),
  aria-label parsing ("From N New Taiwan dollars … total") → cheapest
  single-ticket total + segment-1 times (rows marked separate tickets are
  ignored), and the Playwright `scrape`.
- `providers/fare_db.py` — `FareDatabase` (`public/fares.json`, schema 2:
  per key price / at / prev / hist, `coverage`, `missing`; `merge` keeps 14
  history points and drops entries > 7 days old or already departed) and
  `FareDatabaseProvider`: answers only from the DB (miss → no offer);
  with `LIVE_FARES=1` it prefetches up to `LIVE_FARE_BUDGET` missing
  queries live and saves them back. `SearchService.run` first dry-runs the
  planners on `providers/recording.py` (one placeholder price for every
  query, so nothing is pruned) to learn the full query list.
- `services/crawl_plan.py` + `scripts/build_fare_snapshot.py` — the crawler
  (`.github/workflows/fares-snapshot.yml`, every 6 h; dispatch on the
  branch until merged — schedules only run on the default branch).
  Stage 1: every ow/rt query; stage 2: multi-city queries ranked by the real
  stage-1 prices (四腿票 budget = rt_X + rt_D + rt_Y − ow(TPE→X) − ow(Y→TPE); up to
  3 date variants when ≥ 80% of rt_D, else 1; open jaws by mirrored rt),
  capped at `--max-multi-city`; then a slow retry pass; merged into the DB.
- Demo: `scripts/embed_fare_snapshot.py` writes the DB into
  `<script id="fare-snapshot">` (the workflow does it each run);
  `scripts/export_fare_chunks.py` splits it into `fares/meta` + `fares/cNN`
  docs that Claude writes to the artifact's `db` — the page subscribes and
  replaces the embedded copy when newer. Uncovered airports/holidays are
  marked 無資料; misses are reported, never filled in.

## Live lookups (missing fares, on demand)

No Claude session in the fast path. A search that needs fares the database
lacks shows every database hit immediately, then streams the rest in:

```
page ──POST (<4 KB chunks)──▶ ntfy.sh/<T_REQ> ──▶ scripts/lookup_daemon.py ──▶ Google Flights
page ◀──SSE─────────────────  ntfy.sh/<T_RES> ◀── batches {rid,done,total,fares,nf,final}
```

- `scripts/lookup_daemon.py` runs on GitHub Actions (`.github/workflows/fare-daemon.yml`,
  ~5 h runs restarted by cron every 5 h, one warm Chromium, 5 parallel pages,
  selftest 40 s after start). Requests are validated (`lookup_fares.valid_keys`,
  ≤ 160 keys, ≤ 500 keys / 10 min), results go to `public/fares-live.json`
  (overlay; committed every ~90 s) and the next crawl folds them in.
- THREE daemons run side by side (`fare-daemon.yml` matrix, `Daemon(instance=i)`):
  own IP, browser, tunnels and files (`daemon-<i>.json`, `daemon-status-<i>.json`,
  `fares-live-<i>.json`; instance 0 keeps the legacy names and alone listens to
  ntfy). The page connects to every instance that answers (`connectPeers`) and
  `peersLookup` splits the keys between them round-robin, so a search is ~3x
  faster; a failing share is retried by the others. `load_with_live` folds in
  every `fares-live-*.json`. Scheduled restarts only exist on the default
  branch; lookups need at least one instance online (the page says so when
  `daemon-status.json` is older than 15 min).
- Preferred front door is peer to peer (WebRTC, `rtcEnsure` in the page,
  `Daemon.start_rtc/rtc_answer` with aiortc): the page offers through the ntfy
  topic `<T_REQ>-sig`, the daemon answers on `<T_RES>-sig` (two small
  messages), then lookups and fares flow over a data channel — no tunnel, no
  `daemon.json`, no GitHub API, no ntfy quota for the data. Verified between
  two GitHub runners (`webrtc-probe.yml`) and in the full Pages e2e
  (`via=rtc`). When no peer connection forms in 15 s (symmetric NATs) the page
  falls back to the tunnels below, then ntfy.
- Tunnel front door: the daemon starts TWO independent tunnels (Cloudflare
  quick tunnel via `cloudflared`, and localhost.run via `ssh`) and announces
  them in `public/daemon.json` (`urls`; the page uses the first that answers
  `/health`, tries the other on failure, then ntfy). Anonymous public
  mailboxes (jsonblob, kvdb, restful-api.dev: 50 req/day, …) were probed with
  `relay-probe.yml` and none is usable, so a fully tunnel-free path does not
  exist without an account. Announced in `public/daemon.json`
  (`POST /lookup`, then long-poll `GET /poll/{rid}?i=N` — quick tunnels do
  not carry SSE, so `/events` only serves the python selftest); the page
  discovers it (`discoverDaemon`: raw file with cache-busting query → GitHub
  API → file beside the page; each candidate must pass `/health`) and falls
  back to ntfy (anonymous quota ~250 msgs/day, error 42908). One-minute
  browser check of the direct path: `.github/workflows/tunnel-probe.yml`. `public/daemon-status.json` holds counters + log tail.
  `.github/workflows/fares-fill.yml` + `scripts/fill_fares.py` fill the DB in
  shards (plan → stage1 → merge → stage2 → final).
- Topic names (`T_REQ`/`T_RES`) live in the workflow and `public/index.html`;
  ntfy.sh is a public third-party relay (anyone with the names can post
  requests, keys pass through ntfy). Messages must stay < 4096 bytes.
- Page (`ntfyLookup`, `mergeLiveFares`, `scheduleRefresh`): merges each fare into
  `FARES`, re-runs the search (debounced), caches fares in localStorage
  (`sff.livefares.v1`, 7 days) and keeps them over snapshot swaps.
- Fallback when ntfy is unreachable or the daemon is silent for 45 s: the old
  Claude relay — the page writes `requests/<rid>` to its artifact db and
  fires the poke-only task `WORKER_TRIGGER` (connector *Claude Code Remote*;
  `send_message` is not open to pages). The dev session then runs
  `python -m scripts.relay_lookup dispatch <rid> keys.json` (commits
  `public/live-request.json` → "Fare lookup" workflow posts `fare-lookup`
  commit statuses), mirrors progress into `requests/<rid>`, exports chunks
  (`relay_lookup export`) into `fares/c*` + `fares/meta`, and sets `done`.
- Keys a lookup found nothing for are `unavailable` so pages do not re-ask.

## Scoring

`scoring.score_plans` normalizes four dimensions and takes a weighted sum. The
weights come from the request (user-tunable) and are L1-normalized before use.
Flight-time uses real leg durations plus a per-stop penalty (20 min each).
Risk is the sum of per-warning weights (`low=0.1`, `med=0.4`, `high=1.0`).

## Provider resolution

`SearchService` calls `resolve_default_provider()`:

- `FARE_DB_PATH` (or legacy `FARE_SNAPSHOT_PATH`), else the repo's
  `public/fares.json` → `FareDatabaseProvider` (+ live lookups with
  `LIVE_FARES=1`).
- Else Amadeus (Enterprise keys) / Skyscanner credentials if set.
- Otherwise `NoFareSource` → no plans + a notice. Tests get
  `tests/fake_fares.FakeFareProvider` via `tests/conftest.py`.

Every per-request run wraps the resolved provider in `CachingProvider` for
request-scoped memoization — the single biggest perf lever.

## Frontend data flow

`SearchForm` builds an `ItineraryRequestIn`, calls `api.search(req)` which
hits `/api/search` (Next.js rewrite → FastAPI). `ResultBoard` renders the
plans with per-strategy filter + sort toggle; `PlanCard` shows per-ticket
details and `TimelineView` draws the SVG with red dashed MCT handoff markers.

All API types in `lib/types.ts` mirror backend Pydantic schemas — update
both whenever adding fields.

## Tests

```
pytest -q                     # backend
npm run typecheck && npm run build  # frontend
ruff check . && ruff format .       # backend lint
```

CI runs all of the above on every push touching `smart-flight-finder/**`.

## Common pitfalls

- The `holidays` endpoint falls back to static data when DB is empty — do
  not assume Alembic has run in dev container smoke tests.
- Pydantic validators uppercase every airport code list; if you add a new
  list field (origins-like), extend the `_upper_list` validator in
  `schemas/itinerary.py`.
- The Amadeus adapter uses lazy import inside the resolver to avoid pulling
  in `httpx` at module import time of `services/search.py`.
- When adding a planner, remember to re-run `ruff check` for `I001` import
  ordering — the autofix usually gets it.

## Phase status (current head)

- Phase 1-5 complete.
- Hidden-city planner intentionally not implemented (ethical + legal risk).
- Open follow-ups: Redis-backed cross-request cache; real Skyscanner adapter;
  rate limiting on `/search`; structured JSON logging.

## Plain-HTTP pricing (HTTP first, browser fallback + audit)

`app/providers/google_http.py` prices a key without a browser (≈0.3 s) by posting the page's own `GetShoppingResults`
request (every kind: trip type 2 one-way, 1 round trip, 3 multi-city; no per-search token needed, only the cookies a plain
GET hands out). `Daemon.price()` asks it first (2 tries × 6 s, ≤6 at once) and uses the browser for whatever it cannot read;
10 % of the HTTP prices are also priced by the browser (`HTTP_AUDIT`) and when over 20 % of the last 20-40 disagree by more
than 3 %, HTTP is paused for 30 min. `DAEMON_FAST_FETCH=0` turns it off.

What the experiments (`scripts/exp_http_*.py`, `exp_mc_*.py`, `exp-http-fetch.yml`) found:
* a price "too high" was our parser: Google mixes non-itinerary entries into the itinerary lists and requiring a whole list to
  be itineraries dropped the cheapest flights with it; rows are now recognised one by one;
* midnight times come with a null hour (`[None, 35]`), 20:00 as `[20]`;
* data is missing because Google intermittently hangs ~60 s and then answers `ErrorResponse`; a retry usually works. Measured
  on a runner: one-way ≈ always, round trip 70-90 %, multi-city 10-60 % of keys get data (more concurrency did not help);
* not detected: whether a cheapest row is a "separate tickets" combination (the browser path excludes those);
* Trip.com, Skyscanner, Kayak, Momondo, Expedia, Skiplagged and Wego all refuse plain HTTP from a datacenter IP.

The page has a "查找所有排列組合" button: the normal campaign asks only the likeliest multi-city routes (budgeted); the
button asks every remaining multi-city permutation, spread over the crawlers (`live.campaign.all`).

## Crawler count, dispatch and database safety

`fare-daemon.yml` runs six daemon instances (matrix `[0..5]`, one GitHub job each: own IP, browser, tunnels, `daemon[-i].json`,
`fares-live[-i].json`). The page's `INSTANCES` constant must match the matrix (`test_concurrent_db.py` checks it). Six is a
trade-off, not a limit of the code. The real ceilings: GitHub's concurrent-job cap (≈20 on a free account, shared with the other
workflows), two ntfy signalling messages per instance per page load (anonymous quota ≈250/day per IP) plus one WebRTC connection
each, one git commit stream per instance, and Google's per-IP throttling (more instances on GitHub's shared IP ranges means more
403/429, not more prices). 100+ crawlers would need paid/self-hosted runners and a signalling path that does not scale per page.

**Dispatch** (`app/services/dispatch.py`, JS port `ownerOf` in the page, same test vectors): rendezvous hashing assigns every fare
key to exactly one live instance, identically on every page and run, so no two crawlers fetch the same key; a lost crawler's keys
move to the others and nothing else moves. The page dedupes keys before sharding. Inside a daemon `Daemon.priced` is single-flight
(`inflight` table + TTL cache): a key asked twice at once is fetched once.

**Database** (`app/providers/atomic_io.py`): every file is written atomically (temp + fsync + `os.replace`), so readers and `git add`
never see a torn file. Read-modify-write goes through `FareDatabase.merge_into_file` (`flock` on `<file>.lock`, re-read, merge, save),
so concurrent processes lose no update; `Persister.flush` serialises threads with `flush_lock`. Each instance still owns its own
files (single writer by construction); git pushes use `pull --rebase --autostash` with jittered retries. Workflows that write
`fares.json` keep their `concurrency:` groups.

## One-way screening of multi-city tickets (四腿票 / 反向票＋倒買法)

Measured on real fares (`scripts/exp_mc_vs_ow.py`, 70 multi-city fares priced leg by leg): a multi-city fare is never below the
sum of its one-way legs (lowest ratio 1.04 for two legs, 1.26 for four; median 1.31 / 2.68). Real database check: of 1,613 priced
四腿票 and 1,388 wrap+reverse pairs, **none** beats ordinary round trips (best 1.36x and 1.02x) — Google prices a multi-city
trip about like the sum of its one-ways, so these strategies rarely pay in Google data. One-way fares are fast (HTTP, ~100 %)
and shared by thousands of combinations, so:

* page (`SCREEN`, `oneWayFloor`, `worthAsking`, `planReversePair`, `planFourLegTriple`): a ticket is asked for only when
  0.95 x the sum of its legs' one-way fares leaves room to beat the baseline; unknown legs are asked for first (as normal
  stage-1 one-way keys); the 10 closest pruned calls are still asked (audit) and `checkScreening` switches screening off if
  one comes back below its floor; "查找所有排列組合" (`SCREEN.all`) turns screening off; a user search resets it;
* backend crawl (`crawl_plan.with_leg_keys` / `screen_four_leg`, used by `build_fare_snapshot.py` and `fill_fares.py`): the legs
  join stage 1, 四腿票 keys whose floor reaches the room are dropped (audit sample kept); two-segment keys are not screened
  there (a pair forms a plan);
* browser tuning does not help (`exp_browser_speed.py`: blocking images/fonts or a shorter settle wait changed nothing —
  multi-city pages are slow on Google's side); speed comes from asking less and from more crawlers.

## Airport catalog (Taiwan, China and all of Asia)

`backend/app/data/asia_airports.py` is the table (one line per airport: IATA code | 中文名 | ISO-2 | IANA time zone | group |
gateway flag): 285 scheduled-service airports — Taiwan 18, Japan 44, Korea 12, HK/Macau 2, mainland China 53, South-East
Asia 81, South Asia 38, Central Asia/Mongolia 8, West Asia/Middle East 29. `app/data/airports.py` merges it with the few
long-haul places (Europe/Americas/Oceania) into `TW_ORIGINS` (出發機場 = all Taiwan airports), `DESTINATIONS`, `OUTSTATIONS`
(gateway flag = 四腿票 外站 candidates), `BY_CODE`, `TIMEZONES` (`google_flights.tz_of` reads local times with it, so every
airport needs one) and `COUNTRY_ZH` (picker search by country name). The demo page gets the same table from
`python -m scripts.embed_airports` (rewrites the `AIRPORT-TABLE` block of `public/index.html`; `--check` and
`tests/test_airport_catalog.py` fail when the page is out of date). The page's pickers collapse the Asia-wide lists by group,
have a search box (name / city / code / country) and per-group 全選 / 清除. Airports the fare database does not cover are
marked 無資料 and priced on demand by the crawlers. Trip.com needs metropolitan city codes for multi-airport cities: add them
to `_TRIP_CITY` (`services/booking_links.py`) and `TRIP_CITY` (page) together. The Next.js `frontend/` reads `/airports`.

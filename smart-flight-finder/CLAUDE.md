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

## Two-trip strategies — 反向票＋倒買法 and 外站四腿票

Both only pay off when ONE purchase covers TWO trips, so `SearchService`
runs them over ordered pairs of non-overlapping `candidate_windows`
(trip A strictly before trip B; `_slot_pairs`). With < 2 slots they return
nothing plus a `notices` entry. Shared helpers live in `strategies/two_trip.py`
(`TripSlot`, `quote` → round trip if the two segments mirror, else
`search_multi_city`, `best_pair` constrained cheapest combination).

```
反向票＋倒買法 (reverse.py), home H; each trip has its own in/out city in ONE
country (大阪進東京出); only JP/TH/KR (DAOMAI_COUNTRIES, others → notice):
  包覆票  H→A_in (A start) + B_out→H (B end)   ← or 補頭尾: two one-ways
  反向票  A_out→H (A end)  + H→B_in (B start)  ← foreign-origin, cheap in TW 連假
外站四腿票 (back_to_back.py), one ticket X→TPE→D→TPE→Y, Y in a THIRD country
(not X's, not D's — so the two trips never visit the same country):
  A: 單買初段 TPE→X · stay outer_stay_days · leg1+2 X→TPE→D (<24h at TPE) · leg3 D→TPE
  B: leg4 TPE→Y · 單買最後一段 Y→TPE (or next 四腿票 leg1 = 循環)
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
  stage-1 prices (四腿票 budget = rt_D + rt_Y − ow(TPE→X) − ow(Y→TPE); up to
  3 date variants when ≥ 80% of rt_D, else 1; open jaws by mirrored rt),
  capped at `--max-multi-city`; then a slow retry pass; merged into the DB.
- Demo: `scripts/embed_fare_snapshot.py` writes the DB into
  `<script id="fare-snapshot">` (the workflow does it each run);
  `scripts/export_fare_chunks.py` splits it into `fares/meta` + `fares/cNN`
  docs that Claude writes to the artifact's `db` — the page subscribes and
  replaces the embedded copy when newer. Uncovered airports/holidays are
  marked 無資料; misses are reported, never filled in.

## Live lookups (missing fares, on demand)

When a demo search needs fares the database lacks, the page:
1. writes `requests/<rid>` `{keys, total, status:"queued"}` to its artifact db
   (rule: `requests` read view / write interact), and
2. wakes the dev session through the built-in **Claude Code Remote**
   connector: `fire_trigger` on the poke-only scheduled task `WORKER_TRIGGER`
   (bound to `WORKER_SESSION`, both in `public/index.html`) with text
   `FARE_LOOKUP <rid> …`; `send_message` is the fallback (pages are not
   allowed it on this connector today). If both fail the page stores the
   connector's visible tools in `requests/<rid>.connector_tools`.

The session that receives it (Claude) handles it:
1. `ArtifactData get requests/<rid>` → save `keys` to a file.
2. `python -m scripts.relay_lookup dispatch <rid> keys.json` → validates keys
   (`lookup_fares.valid_keys`, ≤ 160, cheap first), commits
   `public/live-request.json`, pushes, prints the sha. The "Fare lookup"
   workflow (`.github/workflows/fare-lookup.yml`) runs `scripts.lookup_fares`
   for just those keys and posts `fare-lookup` commit statuses `done/total`.
3. Update `requests/<rid>` → `status:"dispatched"`, then Monitor
   `python -m scripts.relay_lookup watch <sha>` and write each line back
   (`running n/N` → `status:"running", done:n`).
4. On `done`: `status:"saving"`, `python -m scripts.relay_lookup export <dir>`
   (pull + chunks of crawl ∪ `fares-live.json`), write `fares/c*` + `fares/meta`
   with a fresh `gen`/`generated_at` (the page swaps data and re-searches),
   then `status:"done", found, not_found`. On `failed`: `status:"error", message`.

Results live in `public/fares-live.json` (overlay, never conflicts with the
crawl; the next crawl folds it in). Keys a lookup found nothing for are listed
as `unavailable` so pages do not re-ask.

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

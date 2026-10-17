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
app/providers/         FlightOfferProvider protocol + Stub, Amadeus, Cache
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
外站四腿票 (back_to_back.py), one ticket X→TPE→D→TPE→Y (Y = X, or 頭尾不同 in X's country):
  A: 單買初段 TPE→X · stay outer_stay_days · leg1+2 X→TPE→D (<24h at TPE) · leg3 D→TPE
  B: leg4 TPE→Y · 單買最後一段 Y→TPE (or next 四腿票 leg1 = 循環)
```

Plans are kept only if cheaper than ordinary round trips for both trips,
carry `ticket_roles` + `trips`, and scoring divides price / flight time /
PTO efficiency by `trip_count` so they compare fairly with single trips.
Tickets carry `searched_segments`; `booking_links` turns open jaws and 3+
segments into multi-city links (mirrored pairs use round-trip links). Link
formats were checked in a real browser — see the module docstring:
Google `tfs` (trip 1/2/3) is exact; Trip.com (tw.trip.com) needs city codes
+ airport params, and multi-city uses its native `multdcity{i}`/
`multacity{i}`/`multddate{i}` URL (what its own search button emits);
Skyscanner gets no multi-city link (bot wall, unverifiable). The demo
(`public/index.html`) mirrors all of this in JS — keep both in sync.

The stub fare model (`providers/stub.py`) makes these strategies
meaningful: +30% on Taiwan-origin departures during 連假, outstation
multi-city through TPE at 0.62× summed one-ways.

## Real fares — Google Flights snapshot

Amadeus Self-Service shut down 2026-07-17, so real prices come from a daily
GitHub Action (`.github/workflows/fares-snapshot.yml`):

1. `services/fare_snapshot.collect_queries` runs `SearchService` against a
   `RecordingProvider` (stub prices) → the exact ow / rt / mc searches the
   planners need for the configured scenario (default TPE → NRT,KIX,LHR,
   outstation HKG, 春節 + 清明 ±1 day; ≈234 searches, dates beyond Google's
   ~330-day horizon dropped).
2. `scripts/build_fare_snapshot.py` opens each as a Google Flights `tfs`
   search (`hl=en&gl=TW&curr=TWD` — without `gl=TW` round trips show no
   results) and parses the result rows' aria-labels ("From N New Taiwan
   dollars … total") → cheapest total + first-segment times.
3. Result is committed to `public/fares.json`. Keys: `ow|O|D|day`,
   `rt|O|D|dep|ret`, `mc|O-D-day|…` (`providers/snapshot.fare_key`; the
   demo JS uses the same strings).

`SnapshotFareProvider` (env `FARE_SNAPSHOT_PATH`) serves it with stub
fallback; offers get `issuer="google_flights"`, later segments carrier
`待選` (Google lists only segment 1 before you pick it). The demo embeds the
snapshot in `<script id="fare-snapshot">` at publish time and shows the
real-fare coverage pill. Some open-jaw searches have no single-ticket result
on Google and stay 示意價. Slow multi-city pages get a second, gentler pass;
a query that still fails keeps the previous snapshot's fare for ≤ 7 days
(`carry_over`, each entry has its own `at`). Plans mixing real fares and
示意價 get a HIGH `mixed_fare_sources` warning (demo + `SearchService`).

## Scoring

`scoring.score_plans` normalizes four dimensions and takes a weighted sum. The
weights come from the request (user-tunable) and are L1-normalized before use.
Flight-time uses real leg durations plus a per-stop penalty (20 min each).
Risk is the sum of per-warning weights (`low=0.1`, `med=0.4`, `high=1.0`).

## Provider resolution

`SearchService` calls `resolve_default_provider()`:

- If `FARE_SNAPSHOT_PATH` points at a `fares.json` → `SnapshotFareProvider`.
- Else if both `AMADEUS_CLIENT_ID` and `AMADEUS_CLIENT_SECRET` are set → use
  `AmadeusProvider` (Enterprise keys only now). Fail-open to
  `StubFlightProvider` on `AmadeusError`.
- Otherwise → `StubFlightProvider` (deterministic prices for dev + tests).

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

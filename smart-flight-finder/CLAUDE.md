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
  `FlightOfferProvider` Protocol. `CachingProvider` wraps it per request; no
  Redis layer yet.

## Date matrix pruning (`date_matrix.py`)

- `expand_window` yields the ± flex candidates (filterable to weekends).
- `iter_date_combos` is the single source of truth for pruning the cartesian
  product:
  - `round_trip`: `min_days_abroad ≤ return − outbound ≤ max_days_abroad?`
  - `multi_city`: strict chronological order across segments.
- Planners either consume `iter_date_combos` or pair dates manually (standard
  does the latter for simpler round-trip code).

## 4-leg (back-to-back) engine — the hard one

Timeline — two independent PNRs with TPE as hub:

```
XMN ─leg1→ TPE ─(MCT handoff)─ TPE ─leg2→ NRT … stay … NRT ─leg3→ TPE ─(MCT)─ TPE ─leg4→ XMN
```

Enumeration order inside `FourLegPlanner.plan`:

1. For each `outer_station × destination`:
2. Pick the baseline (cheapest direct TPE↔destination round-trip across inner
   dates) — plans must undercut it by `MIN_SAVINGS_PCT`.
3. For each inner `(leg2, leg3)` pair with strict order, fetch cheapest inner
   ticket.
4. For each outer `(leg1, leg4)` pair in a `±outer_buffer` window around the
   inner, fetch cheapest outer ticket.
5. Run `check_cross_ticket_handoff` at both junctions — any HIGH risk aborts
   the plan.

Attach `back_to_back_awareness` warning on every surviving plan + an estimated
savings warning.

## Scoring

`scoring.score_plans` normalizes four dimensions and takes a weighted sum. The
weights come from the request (user-tunable) and are L1-normalized before use.
Flight-time uses real leg durations plus a per-stop penalty (20 min each).
Risk is the sum of per-warning weights (`low=0.1`, `med=0.4`, `high=1.0`).

## Provider resolution

`SearchService` calls `resolve_default_provider()`:

- If both `AMADEUS_CLIENT_ID` and `AMADEUS_CLIENT_SECRET` are set → use
  `AmadeusProvider`. Fail-open to `StubFlightProvider` on `AmadeusError`.
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

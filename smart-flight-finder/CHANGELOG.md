# Changelog

All commits on `claude/zealous-darwin-1kexus`, oldest first.

## 2026-10-15 / 2026-10-16

- `790dd47` **Phase 1 scaffold** — repo layout (backend FastAPI + frontend
  Next.js 14), Docker Compose dev stack, Phase 1 data models
  (`ItineraryRequest` / `DateWindow` / `TicketStrategy`), 2027 TW holiday
  + leave-strategy seed data, `/health` + `/holidays/2027` endpoints,
  Alembic skeleton, Next.js landing page.
- `8a22d64` **Phase 2/3 engines** — flexible date-matrix expansion with
  pruning, `FlightOfferProvider` Protocol + `StubFlightProvider`,
  `StandardPlanner` / `ReverseTicketPlanner` / `FourLegPlanner`, MCT
  policy + cross-ticket handoff validator, scoring engine, `POST /search`.
- `8623d28` **Phase 4 UI** — `SearchForm` with holiday quick-select,
  flex sliders, strategy toggles, 4-leg outer-station panel; `ResultBoard`
  with sort/filter; `PlanCard`; `TimelineView` SVG with MCT handoff
  markers; `/holidays` subpage.
- `462fff6` **Phase 5 cache + CI + deploy** — request-scoped
  `CachingProvider` (89% hit on benchmark), Alembic initial migration,
  `scripts/bench_search.py`, GitHub Actions CI, Render blueprint,
  Vercel config.
- `8b2a834` **Open-jaw + Amadeus + UI cache badge** — `OpenJawPlanner`
  pairing distinct destinations; `AmadeusProvider` (OAuth2 +
  flight-offers-search); UI badge showing cache hit rate.
- `585648b` **Multi-city + provider resolver** — `StandardPlanner` grows
  a multi-city branch using `iter_date_combos`; `resolve_default_provider`
  picks Amadeus if configured, Stub otherwise.
- `9d22b4f` **Real flight-time scoring + CLAUDE.md** — scoring uses
  summed leg durations + 20min-per-stop penalty; project architecture
  notes added at `CLAUDE.md`.
- `4ff1a67` **Redis cross-request cache** — `RedisCachingProvider` with
  2h TTL, graceful degradation, resolver stacks it on top of the base.
- `bfbaa6d` **Skyscanner adapter** — RapidAPI shape, overridable host,
  parses the common itineraries→legs→segments tree.
- `61325c6` **Per-IP rate limiter on /search** — fixed window, Redis
  INCR primary with in-process fallback, 429 + Retry-After.
- `_this_` **Final polish** — README status table reflects reality,
  `.env.example` grows provider priority + rate-limit knobs, this
  CHANGELOG.

## Test & lint totals at head

- `pytest -q`: 55 passing
- `ruff check .`: all clean
- `tsc --noEmit`: clean
- `scripts/bench_search.py`: 23ms with 89% cache hit on ±3 flex, 5 dest,
  3 strategies incl. 4-leg

# Changelog

All commits on `claude/zealous-darwin-1kexus`, oldest first (newest summary on top).

## 2026-10-17 — real fares only

- Removed every simulated fare source from the product: prices come only
  from the Google Flights fare database (crawled every 6 h, with price
  history) or live Google Flights lookups; the stub moved to
  `tests/fake_fares.py`. Searches over uncovered airports/dates say so.
- 外站四腿票: trip B (leg 4 + 單買最後一段) lands in a third country — never
  the outstation's or trip A's destination's.
- Crawler: two-stage plan, multi-city queries ranked by real one-way /
  round-trip prices; separate-ticket rows ignored.
- Planners return the closest non-saving plan (flagged) when nothing beats
  ordinary round trips; demo shows coverage, data age, price changes and
  reads the artifact's live fare db.

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
- `416150e` **CHANGELOG + README polish + env knobs** — `.env.example`
  grows provider priority + rate-limit knobs, CHANGELOG seeded.
- `c00d6e5` **Multi-city segments UI + scoring weight sliders** —
  SearchForm swaps to a dynamic segment list for multi-city; collapsible
  weight sliders expose `scoring_weights`.
- `1cac8bd` **N-ticket timeline + iCal export** — TimelineView now
  cycles a 6-color palette for N tickets and only marks cross-ticket
  junctions when both ends sit on the same airport; POST /plans/ics
  + PlanCard "加入日曆" button.
- `33be193` **JSON logging + /metrics Prometheus scrape** — zero-dep
  counters with label escaping; /search emits per-request counters
  including per-strategy breakdown.
- `8c1b65e` **CSV export + Compare panel** — POST /plans/csv flattens
  N plans to one-row-per-leg; frontend adds a selection checkbox,
  Compare toggle, and 2-4 plan side-by-side table.
- `9752f0f` **Admin seed endpoint + readiness probe** — POST
  /admin/seed behind APP_ADMIN_TOKEN; /health/ready pings DB + Redis.
- `08366c6` **Favorites + keyboard shortcuts** — ★ star surfaces
  favorites to the top via localStorage; ⌘Enter submits, Esc closes.
- `a903cfe` **E2E test + shortcuts help modal** — chains
  /search → /plans/{ics,csv} to catch schema drift; `?` toggles help.
- `8a8520d` **Shareable plan URL** — `#p=base64url(JSON)` hash encoding;
  decoded on load, PlanCard copy-to-clipboard with ✓ confirmation.
- `a30b34f` **Price matrix heatmap** — single-hue sequential sky scale
  over outbound × return dates, derived from plans with no backend
  change.
- `37d3434` **Dark-mode toggle** — ThemeToggle cycles system → light →
  dark; Tailwind's hybrid darkMode selector honors both class and
  prefers-color-scheme.
- `971f0e9` **4-leg + open-jaw baseline hoist** — destination-only
  baselines leave the inner loop; CachingProvider was already deduping
  but Python call overhead drops too.
- `5f5bdf4` + `e8bcb71` **Standalone demo + Pages workflow** —
  `smart-flight-finder/public/index.html` is a self-contained HTML
  copy of the UI + strategies; `.github/workflows/pages.yml` at repo
  root with `enablement: true`.
- `95db5ee` **Fix misplaced CI workflow** — ci.yml moves from
  `smart-flight-finder/.github/workflows/` to `.github/workflows/` at
  repo root; prior 10+ commits' CI was dead code.
- `a58a71f` **Docs: Pages activation three paths** — repo visibility,
  reconnect Claude GitHub App, or GitHub Pro.
- `dde5892` **Dependabot** — pip / npm / github-actions / docker on
  weekly + monthly cadences with grouping for Next.js and Tailwind.
- `96efc3c` **4-leg inner_ticket hoist** — second hoist, now the
  inner_ticket fetch also leaves the outer_stations loop. Bench ties:
  6000 → 5520 total calls, 23ms → 19.5ms wall-clock.
- `adbbff4` **Classic `gh-pages` branch** — alternate activation path:
  Settings → Pages → Deploy from branch → gh-pages works without
  needing the Pages API.
- `_this_` **CHANGELOG refresh** — restores historical commits lost
  from the earlier snapshot of this file; aligns totals with HEAD.

## Test & lint totals at head

- `pytest -q`: 69 passing
- `ruff check .`: all clean
- `tsc --noEmit`: clean
- `scripts/bench_search.py`: 19.5ms with 89% cache hit on ±3 flex, 5 dest,
  3 strategies incl. 4-leg (down from 23ms at the Phase 5 baseline)

## Deployment status at HEAD

- **Live demo (Anthropic-hosted)**:
  https://claude.ai/artifact/RzaFsGWZg3phJHoUZYem2F — HTTP 200 confirmed,
  owner-view only until the Artifact's Share menu is used.
- **GitHub Pages (pending user action)**: `.github/workflows/pages.yml`
  and `gh-pages` branch both ready; need repo visibility toggle to
  public or Pages scope on the Claude GitHub App installation.
- **Render + Vercel (ops task)**: `deploy/render.yaml` and
  `frontend/vercel.json` prepared, awaiting the user's accounts.

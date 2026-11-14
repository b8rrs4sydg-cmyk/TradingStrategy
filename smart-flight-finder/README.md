# 智慧化進階機票搜尋與策略規劃系統 (Smart Flight Finder)

> 以「假期」為核心，整合台灣連假、彈性日期矩陣、多段旅程 (Multi-city / Open-Jaw)，
> 以及資深玩家的反向票 (Reverse Ticketing) 與外站四段票 (Back-to-back 4-leg) 策略，
> 自動運算性價比最高、請假效益最大化的機票組合。

本 repo 為 Phase 1 骨架，涵蓋：

- Monorepo 專案結構 (backend FastAPI + frontend Next.js 14)
- Docker Compose 開發環境 (PostgreSQL + Redis + API + Web)
- Phase 1 核心資料模型：`ItineraryRequest` / `DateWindow` / `TicketStrategy`
- 2027 台灣連假與請假攻略靜態資料庫
- `/health` 與 `/holidays/2027` 基本 API

---

## 專案結構

```
smart-flight-finder/
├── backend/                     FastAPI + SQLAlchemy + Alembic
│   ├── app/
│   │   ├── main.py              入口
│   │   ├── config.py            設定
│   │   ├── core/database.py     DB session
│   │   ├── models/              SQLAlchemy ORM (Phase 1 資料模型)
│   │   ├── schemas/             Pydantic schema (API I/O)
│   │   ├── data/                2027 台灣連假靜態資料
│   │   ├── routers/             API endpoints
│   │   └── services/            後續 Phase 2+ 服務層
│   ├── alembic/                 DB migration
│   └── tests/                   pytest
├── frontend/                    Next.js 14 (App Router) + Tailwind
│   ├── app/
│   ├── components/
│   └── lib/
├── docs/
│   ├── spec.md                  完整產品規格書
│   └── roadmap.md               開發階段與里程碑
├── docker-compose.yml
└── .env.example
```

---

## 快速開始

```bash
cp .env.example .env
docker compose up --build
```

- API: http://localhost:8000 (`/docs` 可看 Swagger UI)
- Web: http://localhost:3000
- Postgres: `localhost:5432`，Redis: `localhost:6379`

本地開發 (不走 Docker)：

```bash
# Backend
cd backend
pip install -e .
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

---

## 開發進度 (對應 spec 中的 Phase)

| Phase | 內容 | 狀態 |
|-------|------|------|
| 1     | 專案初始化、Docker、資料模型、2027 連假資料庫 | ✅ |
| 2     | 彈性日期矩陣引擎、FlightOfferProvider 介面 + Stub | ✅ |
| 2.5   | Amadeus adapter + Skyscanner adapter (fallback chain) | ✅ |
| 2.6   | Redis-backed cross-request offer cache + per-IP rate limit | ✅ |
| 3     | Standard (含 multi-city)、Reverse、Open-jaw、Back-to-back 4-leg + MCT 檢查 + 多維度 scoring (真實飛行時長) | ✅ |
| 4     | SearchForm + ResultBoard + PlanCard + Timeline SVG | ✅ |
| 5     | Request-scoped cache、Alembic migration、GitHub Actions CI、Render + Vercel 設定 | ✅ |
| —     | Hidden-city planner | 刻意延後 (法規/道德疑慮) |

---

## Deployment

Two live targets are set up and ready to go:

### 1. GitHub Pages — a public, shareable URL for the static demo

The standalone demo (`smart-flight-finder/public/index.html` — same algorithms,
same seed table, zero backend) deploys via `.github/workflows/pages.yml`.
The workflow is pushed and tried to run; it currently fails with
`Resource not accessible by integration` because the Claude GitHub App
installation on this repo does not have the Pages administration scope.

**One of these three enables the URL below:**

- **Make the repo public** — Settings → General → Change visibility → Make
  public, then Settings → Pages → Build and deployment → Source: GitHub
  Actions. Free, works with the current App permissions. The scaffold
  has no secrets; `.env.example` is a template.
- **Reconnect the Claude GitHub App with Pages scope** at
  https://claude.ai/connect-github, so the workflow's auto-enablement
  works even on a private repo.
- **Upgrade to GitHub Pro** so private-repo Pages is allowed, then enable
  Pages in Settings as above.

Once any of those is done, the next push (or a manual re-run from the
Actions tab) deploys the demo to:

**https://b8rrs4sydg-cmyk.github.io/TradingStrategy/**

### 2. Claude Artifact — a private, logged-in demo that works right now

The same page is published as an Artifact. Works immediately for the owner;
make it shareable through the Share menu inside claude.ai.

Live now: **https://claude.ai/artifact/RzaFsGWZg3phJHoUZYem2F**

### 3. Backend (Render) + Full frontend (Vercel)

For a real deployment with Amadeus/Skyscanner credentials and persistent
Postgres/Redis, follow `deploy/README.md` — the Render blueprint
(`deploy/render.yaml`) and Vercel config (`frontend/vercel.json`) are
prepared, you just need to point them at your accounts.

## Migrating to its own GitHub repo

這份 scaffold 目前放在 `smart-flight-finder/` 子目錄裡，等您在 GitHub 開好 repo 之後，可以用其中一種方式搬過去：

**方法 A：簡單複製**

```bash
cp -r smart-flight-finder /tmp/
cd /tmp/smart-flight-finder
git init && git add -A && git commit -m "chore: initial Phase 1 scaffold"
git remote add origin git@github.com:<you>/smart-flight-finder.git
git push -u origin main
```

**方法 B：保留 commit 歷史 (git subtree)**

```bash
git subtree split --prefix=smart-flight-finder -b flight-split
# 然後把 flight-split 這條分支推到新 repo
```

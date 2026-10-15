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
| 1     | 專案初始化、Docker、資料模型、2027 連假資料庫 | ✅ 本次 |
| 2     | 彈性日期矩陣引擎、Amadeus/Skyscanner 整合、Redis 快取 | ⬜ |
| 3     | 反向票 + 四段票策略引擎 (時間軸碰撞、MCT 檢查) | ⬜ |
| 4     | 前端最佳化看板、Timeline 視覺化 | ⬜ |
| 5     | 壓測、調校、部署 | ⬜ |

---

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

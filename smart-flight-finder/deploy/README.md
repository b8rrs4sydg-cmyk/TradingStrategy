# Deployment

## 開發環境

```bash
docker compose up --build        # Postgres + Redis + API + Web
```

## 雲端部署

### Backend：Render.com

1. 把 `deploy/render.yaml` 匯入 Render Blueprint (需 Render 帳號)。
2. 自動建立：
   - `smart-flight-pg` (Postgres 16 free)
   - `smart-flight-redis` (Redis free)
   - `smart-flight-api` (uvicorn Web Service)
3. 從 Render Shell 跑一次 migration：

   ```bash
   cd smart-flight-finder/backend && alembic upgrade head
   ```

4. 從 Render Shell 執行 seed：

   ```bash
   python - <<'PY'
   from app.core.database import SessionLocal
   from app.services.seed_holidays import seed_holidays
   with SessionLocal() as s:
       print(seed_holidays(s))
   PY
   ```

5. 設定 `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` 等 secret env vars。

### Frontend：Vercel

1. New Project → import `b8rrs4sydg-cmyk/smart-flight-finder`。
2. **Root Directory** 設為 `smart-flight-finder/frontend`。
3. Framework 自動偵測為 Next.js。
4. Env：`NEXT_PUBLIC_API_BASE_URL=https://smart-flight-api.onrender.com`
5. Push 到 `main` 即自動部署。

## CI

`.github/workflows/ci.yml` 在每次對 `smart-flight-finder/**` 的 push / PR 時：

- Backend：`ruff check` + `pytest`
- Frontend：`tsc --noEmit` + `next build`

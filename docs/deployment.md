# Deployment Guide

Target topology (simplest viable for this repo):

| Piece | Service | Notes |
|---|---|---|
| Frontend (Next.js 16) | **Vercel** | root dir `web`, one env var |
| Backend (FastAPI) | **Render** (Railway/Fly.io equivalent) | uvicorn start command, 4–5 env vars |
| Postgres | **Supabase** | session pooler connection string |
| Groq | API only | optional; Fake classifier is the default |

No queues, workers, containers, or auth are required. Uploads are processed in
memory — no local filesystem assumptions.

## 1. Supabase setup

1. Create a project at supabase.com (any region close to your judges).
2. Copy the **Session pooler** connection string
   (Project Settings → Database → Connection string → Session pooler):

   ```
   postgresql://postgres.<proj-ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres?sslmode=require
   ```

3. That string is your backend `DATABASE_URL` as-is. The app normalizes
   `postgresql://` / `postgres://` to SQLAlchemy's `postgresql+psycopg://`
   automatically (`app.config.normalize_database_url`). URL-encode special
   characters in the password.

### Run migrations against Supabase

From `backend/` with the production `DATABASE_URL` set:

```bash
python -m alembic upgrade head
```

Verified: the full chain applies through the scheme-normalization path.
(Alternative on Render: add a release command `cd backend && alembic upgrade head`.)

## 2. Backend deploy (Render)

1. New → Web Service → connect the repo.
2. Root directory: `backend`
3. Build command: `pip install -r requirements.txt`
4. Start command:
   ```bash
   uvicorn app.main:app --host 0.0.0.0 --port $PORT
   ```
   (`gunicorn -k uvicorn.workers.UvicornWorker app.main:app` works identically;
   single worker is enough for a demo.)

### Backend environment variables

| Var | Required | Example / notes |
|---|---|---|
| `DATABASE_URL` | yes | Supabase session-pooler string from step 1 |
| `CORS_ORIGINS` | yes | frontend origin(s), comma-separated: `https://reco-ai.vercel.app,https://reco-ai-git-main.vercel.app` |
| `APP_ENV` | recommended | `production` |
| `GROQ_API_KEY` | optional | enables live classification when set |
| `GROQ_MODEL` | optional | e.g. `llama-3.3-70b-versatile`; both vars must be present |
| `RAZORPAY_WEBHOOK_SECRET` | optional | webhook endpoint fails closed if unset |

Groq gating: `POST /api/exceptions/classify-pending` uses live Groq only when
the request sends `"use_ai": true` AND both Groq env vars exist; otherwise the
deterministic `FakeExceptionClassifier` runs offline. Live Razorpay APIs are
never required — settlements arrive via fixture upload or webhook.

## 3. Frontend deploy (Vercel)

1. New Project → import the repo.
2. Root Directory: `web`
3. Framework preset: Next.js (defaults fine). Node 22.
4. Environment variable:

| Var | Example |
|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `https://<your-backend>.onrender.com` |

5. Deploy. No secrets belong in frontend env — only this public base URL.

## 4. Environment var checklist

Backend (Render):
- [ ] `DATABASE_URL` (Supabase pooler string)
- [ ] `CORS_ORIGINS` (exact Vercel URL(s), https)
- [ ] `APP_ENV=production`
- [ ] `GROQ_API_KEY` + `GROQ_MODEL` (optional pair)
- [ ] `RAZORPAY_WEBHOOK_SECRET` (optional)

Frontend (Vercel):
- [ ] `NEXT_PUBLIC_API_BASE_URL` = backend public URL

Supabase:
- [ ] Project created, connection string copied
- [ ] `alembic upgrade head` applied (check Table Editor shows `transactions`,
      `exceptions`, `audit_logs`, …)

## 5. Demo script flow after deployment

0. Optional — push richer datasets: generate locally with
   `python scripts/generate_test_sets.py` and upload any
   `fixtures/test_sets/<set>/*` instead of `fixtures/synthetic/*`.
   Between sets, reset the environment by running
   `python scripts/reset_demo_data.py` locally with the deployed
   `DATABASE_URL` exported, or redeploy-free truncate via Supabase SQL editor.
1. Open the Vercel dashboard URL — banner shows “Demo mode — single reviewer”.
2. Source uploads panel → upload from `fixtures/synthetic/`:
   - `bank_statement.csv`, `ledger.csv`, `razorpay_settlements.json`
   Expect toasts: inserted 100 / 90 / 95, zero failures.
3. Click **Run reconciliation** → expect 75 matched, 25 exceptions.
4. Click **Classify pending (offline demo)** → 25 classified by `fake`.
   For a live-AI moment set the Groq env vars, redeploy backend, and use the
   same button after clearing `use_ai` semantics — or call
   `POST /api/exceptions/classify-pending {"use_ai": true}` directly.
5. Open **Exceptions** → pick an unresolved row → verify facts → evidence →
   AI hypothesis order → Approve / Reject / Manual Override (reason required
   for the latter two).
6. Run detail page shows match groups + evaluation metrics
   (expect all five = 100% on the fixed batch).

## 6. Smoke commands

```bash
# backend health (local or deployed)
curl -s https://<backend-domain>/health          # {"status":"ok","database":"ok"}

# deployed CORS check (must echo your Vercel origin)
curl -s -i -X OPTIONS https://<backend-domain>/api/exceptions/classify-pending \
  -H "Origin: https://<frontend-domain>" \
  -H "Access-Control-Request-Method: POST" | grep -i access-control-allow-origin

# frontend build (local gate before push)
cd web && npm run build

# backend tests (no external services needed)
cd backend && python -m pytest tests -v
```

## 7. Known non-goals

- No authentication/billing/multi-user authorization (demo actor only).
- No live Razorpay API polling or `settlement.created` webhooks.
- No background workers/queues, Docker production infra, autoscaling claims.
- Single-region demo; transaction-pooler port 6543 not used for DDL.

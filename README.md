# Reco.ai — AI Finance Controller (demo)

Deterministic-first reconciliation across Razorpay settlements, bank statements,
and an internal ledger, with AI classification reserved for unresolved residue and
a human-approved audit trail.

**Demo mode — single reviewer** (`demo_finance_controller`). Not production auth.
All data in this repository is **synthetic**; no live merchant or customer data is
included. See `docs/contracts/README.md` and the statement below.

## Stack

- Backend: FastAPI + SQLAlchemy 2.x + Alembic + Pandas + Pydantic (Postgres 16 via Docker)
- Frontend: Next.js 16 (Node 22) + Tailwind + shadcn/ui + lucide-react
- LLM (optional): Groq behind the `ExceptionClassifier` interface; tests never call it

## Quickstart (one command)

```bash
# prerequisites: Docker running, Python 3.12+, Node 22, backend venv active
cp .env.example .env            # set POSTGRES_PASSWORD (local only)
python scripts/run_demo.py      # add --skip-docker if Postgres is already up
```

The script: starts Postgres → migrates to head → regenerates deterministic
fixtures → starts backend (:8000) and frontend (:3000) → ingests fixtures →
runs reconciliation → classifies residue (Fake classifier offline; Groq live
only if `GROQ_API_KEY` + `GROQ_MODEL` are set) → prints evaluation metrics and
opens the dashboard.

**Deploying publicly?** See [`docs/deployment.md`](docs/deployment.md)
(Vercel + Render + Supabase + Groq env setup).

## Multiple difficulty test sets

```powershell
python scripts/generate_test_sets.py          # writes fixtures/test_sets/{clean,balanced,messy,stress}
python scripts/reset_demo_data.py             # wipe runtime data between uploads
```

Each set is 100 cases with a different issue density (15% / 40% / 65% / 80%).
Upload one set via the dashboard, run reconciliation + classification, then
reset before the next set so results stay clean.

## Manual flow

```bash
docker compose up -d                       # Postgres on :5432
cd backend && python -m alembic upgrade head

# generate fixtures deterministically (seeded)
python scripts/generate_synthetic_data.py --seed 42

# start services
cd backend && python -m uvicorn app.main:app --port 8000
cd web && npm install && npm run build && npm run start   # or npm run dev
```

Then upload `fixtures/synthetic/*.csv|json` from the dashboard's Source uploads
panel (or let `scripts/run_demo.py` do it), press **Run reconciliation**, then
**Classify pending (offline demo)**.

## Tests

```bash
cd backend && python -m pytest tests -v    # 98 tests; no live Razorpay/Groq calls
cd web && npm run lint && npm run build
```

CI-safe by design: webhooks are tested with locally computed HMAC signatures, the
LLM layer uses `FakeExceptionClassifier` and scripted transports.

## Evaluation metrics (reported separately, never weighted together)

- Deterministic Match Score = correct auto-matches / auto-matches
- Deterministic Coverage = auto-matches / eligible matchable cases
- Exception Recall = surfaced known exceptions / known exceptions
- AI Classification Accuracy = correct AI classifications / AI-classified cases
- LLM Faithfulness Score = mean evidence-support across evaluated explanations

Ground truth lives only in `fixtures/synthetic/ground_truth.json` and is read
exclusively by the evaluation service (`backend/app/services/evaluation/metrics.py`)
— never by the matcher, prompts, or UI.

## Repository layout

```
backend/app          FastAPI app (routers, models, services)
backend/alembic      migrations
web                  Next.js dashboard
fixtures/synthetic   generated demo batch (100 cases) + ground_truth.json
scripts              generate_synthetic_data.py · run_demo.py
docs/contracts       Razorpay payload contract fixtures (synthetic)
docs/judge_defense.md  answers to the standard buildathon challenges
```

## Non-goals

No Prisma, no auto-ledger posting by AI, no fake `settlement.created` webhook,
no multi-user authorization, no invented rubric weights.

# Reco.ai Agent Guardrails

Use this file as the source of truth for implementation decisions.

- Build the project in phases. Do not advance a phase until its tests and exit checks pass.
- Backend uses FastAPI, SQLAlchemy 2.x, Alembic, Pandas, Pydantic, and a classifier interface. Do not add Prisma.
- Store all money as integer paise using `BIGINT`. Do not use floats for money conversion or matching.
- Keep ground truth labels isolated in evaluation fixtures only. Never include labels in raw payloads, transaction IDs, narration, prompts, or LLM inputs.
- Deterministic matching runs before AI: exact unique UTR plus amount, unique amount plus date window, and known fee/refund equations.
- Duplicate UTRs, ambiguous candidates, currency mismatches, and unknown credits must not auto-match.
- LLM handles only unmatched residue and must return strict structured JSON through Pydantic validation.
- Provide a `FakeExceptionClassifier` for tests and demos. CI must not call live Groq.
- LLM failure modes must become explicit exception categories such as `MODEL_UNAVAILABLE` or `INVALID_MODEL_OUTPUT`.
- Webhooks must verify Razorpay signatures over the raw body and dedupe by event id.
- UI uses Next.js, Tailwind, shadcn/ui, and lucide-react. Keep dashboard screens dense, operational, and audit-focused.
- Audit logs are append-only. Approve, reject, and manual override actions must preserve the AI hypothesis and human reason.

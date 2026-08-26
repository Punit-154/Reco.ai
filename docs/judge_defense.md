# Judge Defense

## 1. Why deterministic first, AI second?

Money matching is a solvable arithmetic problem whenever the evidence is
sufficient, so it should never be probabilistic. Reco.ai runs three strict,
ordered strategies before any model is consulted:

1. `EXACT_UTR_AMOUNT` — unique normalized UTR **and** exact paise amount;
2. `AMOUNT_DATE_WINDOW` — unique amount within ±2 days when no UTR exists;
3. `LEDGER_NET_EXACT` — ledger net (gross − fee − tax − refund) equals the bank
   credit with matching Razorpay fee/tax evidence.

Anything that survives these strategies is residue by construction: duplicate
UTRs, ambiguous candidates, currency mismatches, and unknown credits are
**never auto-matched** — they become review exceptions (`AMBIGUOUS_MATCH`,
`PENDING_AI_REVIEW`). The LLM's only job is to explain residue and recommend a
next step for a human; it cannot post ledger entries or create match groups.
On the fixed 100-case batch this split yields 75% deterministic coverage with
zero AI involvement where evidence suffices.

## 2. How do we prevent hallucinated reconciliation?

- **Strict structured output**: the model must return Pydantic-validated JSON
  (`ExceptionClassification`, `extra="forbid"`, bounded confidence 0–100).
  Invalid JSON gets exactly one repair retry, then becomes an explicit
  `INVALID_MODEL_OUTPUT` exception — never a guessed classification.
- **Evidence-bounded prompts**: prompts contain only unmatched transaction
  facts (amounts in integer paise, dates, UTRs, candidate deltas). A regression
  test scans every prompt and payload fixture for forbidden label keys
  (`scenario`, `expected_class`, `duplicate_flag`, …); ground truth physically
  never reaches the matcher or the LLM.
- **Citation checking**: every AI explanation cites transaction IDs; a
  deterministic faithfulness checker verifies cited IDs exist and are linked to
  the exception. Unsupported citations lower `llm_faithfulness_score` and are
  visible on the review card.
- **No silent state change**: AI writes only hypothesis fields on the exception
  row (`response`, `confidence`, `model_name`). Status stays `unresolved`
  until a human approves, rejects, or overrides — the UI shows source facts and
  deterministic evidence *before* any AI prose.

## 3. How do we handle failure recovery and auditability?

- **Webhooks fail safe**: `X-Razorpay-Signature` HMAC-SHA256 is verified over
  the **raw body** before parsing; events dedupe on `x-razorpay-event-id`;
  the raw event is persisted before processing. If settlement normalization
  fails, the event stays stored with `processed_at = NULL` — an observable,
  retryable state. Nothing is dropped silently.
- **LLM failure is a first-class outcome**: timeouts and provider errors retry
  once (bounded concurrency of 3) and then surface as `MODEL_UNAVAILABLE`
  exceptions with `retry_count` incremented, so degraded runs stay honest and
  re-classifiable instead of inventing answers.
- **Append-only audit trail**: every approve / reject / manual override writes
  one `audit_logs` row inside the same database transaction as the status
  change, preserving the full AI hypothesis, previous/new state, and the human
  reason. A Postgres trigger makes `audit_logs` physically immune to UPDATE
  and DELETE — verified by tests.
- **Reproducibility**: fixtures regenerate byte-identically from a fixed seed;
  evaluation metrics are computed from isolated ground truth and stored per
  `evaluation_runs` row, so any reported number can be replayed.

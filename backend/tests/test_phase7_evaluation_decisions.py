import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.models import AuditLog, EvaluationRun, ExceptionRecord, MatchGroup
from app.services.ai.classifier import (
    ExceptionClassification,
    FakeExceptionClassifier,
)
from app.services.ai.triage import classify_pending_exceptions
from app.services.evaluation.metrics import (
    DeterministicEvidenceChecker,
    LlmJudgeEvaluator,
    load_ground_truth,
    run_evaluation,
)
from app.services.ingestion.importers import (
    ingest_bank_csv,
    ingest_ledger_csv,
    ingest_razorpay_settlements,
)
from app.services.matching.deterministic import start_reconciliation_run

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "fixtures" / "synthetic"
GROUND_TRUTH_PATH = FIXTURES_DIR / "ground_truth.json"


@pytest.fixture()
def pipeline_loaded(client, clean_tables, engine, session_factory):
    with session_factory() as db:
        ingest_bank_csv(db, (FIXTURES_DIR / "bank_statement.csv").read_bytes())
        ingest_ledger_csv(db, (FIXTURES_DIR / "ledger.csv").read_bytes())
        ingest_razorpay_settlements(
            db, (FIXTURES_DIR / "razorpay_settlements.json").read_bytes()
        )
        run_result = start_reconciliation_run(db)
        db.commit()

        classify_pending_exceptions(db, FakeExceptionClassifier(), limit=100)
        db.commit()

    return {
        "session_factory": session_factory,
        "client": client,
        "engine": engine,
        "run_id": uuid.UUID(run_result["run_id"]),
    }


def _exceptions(sf):
    with sf() as db:
        return db.execute(select(ExceptionRecord)).scalars().all()


def test_metrics_match_synthetic_expected_counts(pipeline_loaded):
    sf = pipeline_loaded["session_factory"]
    with sf() as db:
        output = run_evaluation(
            db, GROUND_TRUTH_PATH, reconciliation_run_id=pipeline_loaded["run_id"]
        )
        db.commit()

    m = output.metrics
    assert m["total_cases"] == 100
    assert m["deterministic_match_rate"] == 1.0
    assert m["deterministic_coverage"] == 1.0
    assert m["exception_recall"] == 1.0
    assert m["ai_classification_accuracy"] == 1.0
    assert m["llm_faithfulness_score"] == 1.0

    c = m["counts"]
    assert c["eligible_matchable_cases"] == 75
    assert c["deterministic_auto_matches"] == 75
    assert c["correct_auto_matches"] == 75
    assert c["known_exception_cases"] == 25
    assert c["surfaced_exceptions"] == 25
    assert c["ai_classified"] == 25
    assert c["ai_correct"] == 25

    with sf() as db:
        runs = db.execute(select(EvaluationRun)).scalars().all()
    assert len(runs) == 1
    assert runs[0].seed == 42
    assert runs[0].fixture_version == "synthetic-v1"


def test_metrics_are_zero_safe_without_data(clean_tables, session_factory):
    del clean_tables
    with session_factory() as db:
        output = run_evaluation(
            db, GROUND_TRUTH_PATH, reconciliation_run_id=uuid.uuid4()
        )
        db.commit()
    m = output.metrics
    for rate in (
        m["deterministic_match_rate"],
        m["deterministic_coverage"],
        m["exception_recall"],
        m["ai_classification_accuracy"],
        m["llm_faithfulness_score"],
    ):
        assert rate == 0.0


def test_evaluation_reads_ground_truth_only_in_evaluation_layer():
    evaluation_src = (
        REPO_ROOT / "backend" / "app" / "services" / "evaluation" / "metrics.py"
    ).read_text(encoding="utf-8")
    assert "load_ground_truth" in evaluation_src or "ground_truth_path" in evaluation_src

    for module in [
        REPO_ROOT / "backend" / "app" / "services" / "matching" / "deterministic.py",
        REPO_ROOT / "backend" / "app" / "services" / "ai" / "classifier.py",
        REPO_ROOT / "backend" / "app" / "services" / "ai" / "triage.py",
        REPO_ROOT / "backend" / "app" / "services" / "ai" / "evidence.py",
    ]:
        text_content = module.read_text(encoding="utf-8").lower()
        assert "ground_truth" not in text_content, f"{module.name} references ground_truth"
        assert "fixtures/" not in text_content


def test_faithfulness_checker_and_llm_placeholder(pipeline_loaded):
    sf = pipeline_loaded["session_factory"]
    checker = DeterministicEvidenceChecker()

    with sf() as db:
        rows = db.execute(select(ExceptionRecord)).scalars().all()
        classified = [r for r in rows if r.response is not None]
        exc = classified[0]
        classification = __import__(
            "app.services.ai.classifier", fromlist=["ExceptionClassification"]
        ).ExceptionClassification.model_validate(exc.response)

        good_score = checker.score(db, exc, classification)

        tampered = classification.model_copy(
            update={
                "evidence_transaction_ids": classification.evidence_transaction_ids
                + [str(uuid.uuid4())]
            }
        )
        partial_score = checker.score(db, exc, tampered)

        empty_score = checker.score(
            db, exc, classification.model_copy(update={"evidence_transaction_ids": []})
        )

    assert good_score == 1.0
    assert 0.0 <= partial_score < 1.0
    assert empty_score == 0.0

    judge = LlmJudgeEvaluator()
    with pytest.raises(NotImplementedError):
        judge.score(None, None, None)


def test_run_metrics_endpoint_returns_summary_and_evaluation(pipeline_loaded):
    client = pipeline_loaded["client"]
    run_id = pipeline_loaded["run_id"]

    response = client.get(f"/api/reconciliation-runs/{run_id}/metrics")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["reconciliation_run_id"] == str(run_id)
    assert body["summary"]["matched_bank_transactions"] == 75
    ev = body["evaluation"]
    assert ev is not None
    assert ev["metrics"]["deterministic_match_rate"] == 1.0
    assert ev["metrics"]["counts"]["surfaced_exceptions"] == 25

    second = client.get(f"/api/reconciliation-runs/{run_id}/metrics").json()
    assert second["evaluation"]["evaluation_run_id"] == ev["evaluation_run_id"]


def test_unknown_run_metrics_404(client):
    response = client.get(f"/api/reconciliation-runs/{uuid.uuid4()}/metrics")
    assert response.status_code == 404


@pytest.mark.usefixtures("clean_tables")
def test_exception_detail_endpoint(client, session_factory):
    with session_factory() as db:
        ingest_bank_csv(db, (FIXTURES_DIR / "bank_statement.csv").read_bytes())
        ingest_ledger_csv(db, (FIXTURES_DIR / "ledger.csv").read_bytes())
        ingest_razorpay_settlements(
            db, (FIXTURES_DIR / "razorpay_settlements.json").read_bytes()
        )
        start_reconciliation_run(db)
        db.commit()

    rows = _exceptions(session_factory)
    target = rows[0]

    detail = client.get(f"/api/exceptions/{target.id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == str(target.id)
    assert body["taxonomy"] in ("PENDING_AI_REVIEW", "AMBIGUOUS_MATCH")
    assert body["evidence"]["reason_code"]

    missing = client.get(f"/api/exceptions/{uuid.uuid4()}")
    assert missing.status_code == 404


def _decide(client, exc, payload):
    return client.post(f"/api/exceptions/{exc.id}/decision", json=payload)


def test_approve_creates_audit_row_preserving_ai_hypothesis(pipeline_loaded):
    sf = pipeline_loaded["session_factory"]
    client = pipeline_loaded["client"]

    rows = _exceptions(sf)
    target = next(r for r in rows if r.response is not None)
    hypothesis_before = json.dumps(target.response, sort_keys=True)

    response = _decide(client, target, {"action": "approve"})
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["exception"]["status"] == "approved"
    audit = body["audit_event"]
    assert audit["action"] == "exception_approve"
    assert json.dumps(audit["ai_hypothesis"], sort_keys=True) == hypothesis_before
    assert audit["previous_state"]["status"] == "unresolved"

    with sf() as db:
        logs = db.execute(
            select(AuditLog).where(AuditLog.entity_type == "exception")
        ).scalars().all()
        updated = db.get(ExceptionRecord, target.id)
    assert len(logs) == 1
    assert json.dumps(logs[0].ai_hypothesis, sort_keys=True) == hypothesis_before
    assert updated.status == "approved"


def test_reject_requires_reason(pipeline_loaded):
    client = pipeline_loaded["client"]
    target = _exceptions(pipeline_loaded["session_factory"])[0]

    missing = _decide(client, target, {"action": "reject"})
    assert missing.status_code == 422
    assert "reason" in missing.json()["detail"].lower()

    ok = _decide(client, target, {"action": "reject", "reason": "evidence insufficient"})
    assert ok.status_code == 200
    assert ok.json()["exception"]["status"] == "rejected"
    assert ok.json()["audit_event"]["reason"] == "evidence insufficient"


def test_manual_override_sets_category_and_reason_required(pipeline_loaded):
    sf = pipeline_loaded["session_factory"]
    client = pipeline_loaded["client"]

    rows = _exceptions(sf)
    target = next(
        r
        for r in rows
        if r.response and r.response["category"] == "REFUND_LAG"
    )

    no_reason = _decide(
        client,
        target,
        {"action": "manual_override", "override_category": "FEE_DELTA"},
    )
    assert no_reason.status_code == 422

    bad_category = _decide(
        client,
        target,
        {"action": "manual_override", "reason": "misread the ledger", "override_category": "NOT_REAL"},
    )
    assert bad_category.status_code == 422

    ok = _decide(
        client,
        target,
        {
            "action": "manual_override",
            "reason": "ledger shows fee correction not refund lag",
            "override_category": "FEE_DELTA",
        },
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["exception"]["status"] == "overridden"
    assert body["exception"]["taxonomy"] == "FEE_DELTA"

    hypothesis_before = json.dumps(target.response, sort_keys=True)
    assert json.dumps(body["audit_event"]["ai_hypothesis"], sort_keys=True) == hypothesis_before
    assert body["audit_event"]["new_state"]["override_category"] == "FEE_DELTA"


def test_double_decision_conflicts(pipeline_loaded):
    client = pipeline_loaded["client"]
    target = _exceptions(pipeline_loaded["session_factory"])[0]

    first = _decide(client, target, {"action": "approve"})
    assert first.status_code == 200

    second = _decide(client, target, {"action": "reject", "reason": "changed my mind"})
    assert second.status_code == 409


def test_audit_logs_cannot_be_updated_or_deleted(pipeline_loaded):
    engine = pipeline_loaded["engine"]
    sf = pipeline_loaded["session_factory"]

    actor_uuid = uuid.UUID("7fa528e3-07b7-5613-b90d-e89b562882a3")
    with sf() as db:
        db.add(
            AuditLog(
                actor_id=actor_uuid,
                action="immutability_probe",
                entity_type="exception",
                entity_id=str(uuid.uuid4()),
                new_state={"v": 1},
            )
        )
        db.commit()

    with engine.connect() as conn:
        count = conn.execute(text("select count(*) from audit_logs")).scalar()
        assert count == 1

        with pytest.raises(DBAPIError):
            conn.execute(text("UPDATE audit_logs SET action = 'tampered'"))
            conn.commit()

        with pytest.raises(DBAPIError):
            conn.execute(text("DELETE FROM audit_logs"))
            conn.commit()


def test_decisions_do_not_touch_match_groups(pipeline_loaded):
    sf = pipeline_loaded["session_factory"]
    client = pipeline_loaded["client"]

    with sf() as db:
        before = len(db.execute(select(MatchGroup)).scalars().all())

    target = _exceptions(sf)[0]
    response = _decide(client, target, {"action": "approve"})
    assert response.status_code == 200

    with sf() as db:
        after = len(db.execute(select(MatchGroup)).scalars().all())
    assert before == after == 75

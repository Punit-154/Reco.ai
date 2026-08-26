import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import ExceptionRecord, MatchGroup, MatchMember, Transaction
from app.services.evaluation.synthetic_generator import find_label_leaks
from app.services.ingestion.importers import (
    ingest_bank_csv,
    ingest_ledger_csv,
    ingest_razorpay_settlements,
)
from app.services.matching.deterministic import (
    CATEGORY_AMBIGUOUS_MATCH,
    CATEGORY_PENDING_AI_REVIEW,
    STRATEGY_EXACT_UTR_AMOUNT,
    STRATEGY_LEDGER_NET_EXACT,
    start_reconciliation_run,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "fixtures" / "synthetic"
MATCHER_SOURCE = (
    REPO_ROOT / "backend" / "app" / "services" / "matching" / "deterministic.py"
).read_text(encoding="utf-8")

GROUND_TRUTH = json.loads((FIXTURES_DIR / "ground_truth.json").read_text(encoding="utf-8"))


@pytest.fixture()
def loaded_case(client, clean_tables, engine, session_factory):
    def _ingest():
        with session_factory() as db:
            ingest_bank_csv(db, (FIXTURES_DIR / "bank_statement.csv").read_bytes())
            ingest_ledger_csv(db, (FIXTURES_DIR / "ledger.csv").read_bytes())
            ingest_razorpay_settlements(
                db, (FIXTURES_DIR / "razorpay_settlements.json").read_bytes()
            )
            db.commit()

    _ingest()
    return {
        "engine": engine,
        "session_factory": session_factory,
        "client": client,
    }


def _run(session_factory) -> dict:
    with session_factory() as db:
        result = start_reconciliation_run(db)
        db.commit()
    return result


def test_fixture_batch_matches_deterministically(loaded_case):
    result = _run(loaded_case["session_factory"])
    s = result["summary"]
    assert s["total_bank_transactions"] == 100
    assert s["matched_bank_transactions"] == 75
    assert s["unmatched_bank_transactions"] == 25
    assert s["deterministic_match_rate"] == 0.75
    assert s["strategy_counts"] == {
        STRATEGY_EXACT_UTR_AMOUNT: 60,
        STRATEGY_LEDGER_NET_EXACT: 15,
    }
    assert s["exceptions_created"] == 25
    assert s["exceptions_by_category"] == {
        CATEGORY_PENDING_AI_REVIEW: 20,
        CATEGORY_AMBIGUOUS_MATCH: 5,
    }


def test_perfect_and_fee_cases_match_with_expected_strategy(loaded_case):
    _run(loaded_case["session_factory"])
    sf = loaded_case["session_factory"]
    with sf() as db:
        txn_by_external = {
            t.external_id: t for t in db.execute(select(Transaction)).scalars().all()
        }
        groups = db.execute(select(MatchGroup)).scalars().all()
        members = db.execute(select(MatchMember)).scalars().all()

    group_by_id = {g.id: g for g in groups}
    member_by_group: dict = {}
    group_of_txn: dict = {}
    for m in members:
        member_by_group.setdefault(m.match_group_id, []).append(m)
        group_of_txn[m.transaction_id] = group_by_id[m.match_group_id]

    assert {g.strategy for g in groups} == {
        STRATEGY_EXACT_UTR_AMOUNT,
        STRATEGY_LEDGER_NET_EXACT,
    }

    for case in GROUND_TRUTH["cases"].values():
        if case["case_type"] not in ("perfect_match", "fee_deduction"):
            continue
        bank_id = txn_by_external[case["source_ids"]["bank"][0]].id
        settlement_ids = [txn_by_external[e].id for e in case["source_ids"]["razorpay"]]
        ledger_id = txn_by_external[case["source_ids"]["ledger"][0]].id

        group = group_of_txn[bank_id]
        assert group.strategy == (
            STRATEGY_EXACT_UTR_AMOUNT
            if case["case_type"] == "perfect_match"
            else STRATEGY_LEDGER_NET_EXACT
        )
        member_txns = {m.transaction_id for m in member_by_group[group.id]}
        assert member_txns == {bank_id} | set(settlement_ids) | {ledger_id}
        assert group.delta_paise == 0
        assert group.actual_amount_paise == group.expected_amount_paise


def test_duplicate_utr_cases_do_not_auto_match(loaded_case):
    _run(loaded_case["session_factory"])
    sf = loaded_case["session_factory"]
    with sf() as db:
        txn_by_external = {
            t.external_id: t for t in db.execute(select(Transaction)).scalars().all()
        }
        member_ids = set(db.execute(select(MatchMember.transaction_id)).scalars().all())
        ambiguous = db.execute(
            select(ExceptionRecord).where(ExceptionRecord.taxonomy == CATEGORY_AMBIGUOUS_MATCH)
        ).scalars().all()

    dup_exceptions = 0
    for case in GROUND_TRUTH["cases"].values():
        if case["case_type"] != "duplicate_utr":
            continue
        settlement_ids = [txn_by_external[e].id for e in case["source_ids"]["razorpay"]]
        assert not set(settlement_ids) & member_ids
        bank_id = txn_by_external[case["source_ids"]["bank"][0]].id
        assert bank_id not in member_ids

        exc = next(e for e in ambiguous if e.transaction_id == bank_id)
        assert exc.evidence["reason_code"] == "MULTIPLE_SETTLEMENT_CANDIDATES"
        assert len(exc.evidence["related_settlement_transaction_ids"]) == 2
        dup_exceptions += 1

    assert dup_exceptions == 5
    assert len(ambiguous) == 5


def test_unrecognized_credits_become_exceptions(loaded_case):
    _run(loaded_case["session_factory"])
    sf = loaded_case["session_factory"]
    with sf() as db:
        txn_by_external = {
            t.external_id: t for t in db.execute(select(Transaction)).scalars().all()
        }
        member_ids = set(db.execute(select(MatchMember.transaction_id)).scalars().all())
        exceptions = db.execute(select(ExceptionRecord)).scalars().all()
    exception_by_txn = {e.transaction_id: e for e in exceptions}

    unrec_count = 0
    for case in GROUND_TRUTH["cases"].values():
        if case["case_type"] != "unrecognized_credit":
            continue
        bank_id = txn_by_external[case["source_ids"]["bank"][0]].id
        assert bank_id not in member_ids
        exc = exception_by_txn[bank_id]
        assert exc.taxonomy == CATEGORY_PENDING_AI_REVIEW
        assert exc.status == "unresolved"
        assert exc.evidence["reason_code"] == "NO_CANDIDATE"
        unrec_count += 1
    assert unrec_count == 10


def test_partial_refunds_become_residue_not_matches(loaded_case):
    _run(loaded_case["session_factory"])
    sf = loaded_case["session_factory"]
    with sf() as db:
        txn_by_external = {
            t.external_id: t for t in db.execute(select(Transaction)).scalars().all()
        }
        member_ids = set(db.execute(select(MatchMember.transaction_id)).scalars().all())
        exceptions = db.execute(select(ExceptionRecord)).scalars().all()
    exception_by_txn = {e.transaction_id: e for e in exceptions}

    refund_count = 0
    for case in GROUND_TRUTH["cases"].values():
        if case["case_type"] != "partial_refund":
            continue
        involved = [
            txn_by_external[e].id
            for e in case["source_ids"]["bank"]
            + case["source_ids"]["razorpay"]
            + case["source_ids"]["ledger"]
        ]
        assert not set(involved) & member_ids, "partial refund cluster was auto-matched"

        exc = exception_by_txn[involved[0]]
        assert exc.taxonomy == CATEGORY_PENDING_AI_REVIEW
        refund_count += 1
    assert refund_count == 10


def test_matcher_twice_is_idempotent(loaded_case):
    first = _run(loaded_case["session_factory"])
    second = _run(loaded_case["session_factory"])

    assert second["summary"]["match_groups_created"] == 0
    assert second["summary"]["exceptions_created"] == 0
    assert second["summary"]["strategy_counts"] == first["summary"]["strategy_counts"]
    assert second["summary"]["matched_bank_transactions"] == first["summary"]["matched_bank_transactions"]

    sf = loaded_case["session_factory"]
    with sf() as db:
        groups = db.execute(select(MatchGroup)).scalars().all()
        exceptions = db.execute(select(ExceptionRecord)).scalars().all()
    assert len(groups) == 75
    assert len(exceptions) == 25


def test_matcher_never_reads_ground_truth():
    lowered = MATCHER_SOURCE.lower()
    assert "ground_truth" not in lowered
    assert "fixtures/" not in lowered
    assert "services.evaluation" not in lowered.replace("app.services", "")


def test_match_members_link_all_relevant_transactions(loaded_case):
    _run(loaded_case["session_factory"])
    sf = loaded_case["session_factory"]
    with sf() as db:
        groups = db.execute(select(MatchGroup)).scalars().all()
        members = db.execute(select(MatchMember)).scalars().all()
        txns = {t.id: t for t in db.execute(select(Transaction)).scalars().all()}

    members_by_group: dict = {}
    for m in members:
        members_by_group.setdefault(m.match_group_id, []).append(m)

    assert len(groups) == len(members_by_group) == 75
    for group in groups:
        rows = members_by_group[group.id]
        roles = {r.role for r in rows}
        assert roles == {"bank_credit", "razorpay_settlement", "ledger_entry"}
        assert group.actual_amount_paise == group.expected_amount_paise
        assert group.delta_paise == 0
        for r in rows:
            assert r.allocated_paise == txns[r.transaction_id].amount_paise
            assert isinstance(r.allocated_paise, int)
        assert all(r.transaction_id in txns for r in rows)


def test_no_llm_fields_on_deterministic_exceptions(loaded_case):
    _run(loaded_case["session_factory"])
    sf = loaded_case["session_factory"]
    with sf() as db:
        exceptions = db.execute(select(ExceptionRecord)).scalars().all()
    assert len(exceptions) > 0
    for exc in exceptions:
        assert exc.model_name is None
        assert exc.prompt_version is None
        assert exc.response is None
        assert exc.confidence is None
        assert exc.status == "unresolved"


def test_reconciliation_endpoints(loaded_case):
    response = loaded_case["client"].post("/api/reconciliation-runs")
    assert response.status_code == 201, response.text
    body = response.json()
    run_id = body["run_id"]
    assert body["status"] == "completed"
    assert body["summary"]["matched_bank_transactions"] == 75

    fetched = loaded_case["client"].get(f"/api/reconciliation-runs/{run_id}")
    assert fetched.status_code == 200
    assert fetched.json()["summary"]["deterministic_match_rate"] == 0.75

    missing = loaded_case["client"].get(f"/api/reconciliation-runs/{uuid.uuid4()}")
    assert missing.status_code == 404


def test_exception_evidence_has_no_labels(loaded_case):
    _run(loaded_case["session_factory"])
    sf = loaded_case["session_factory"]
    with sf() as db:
        exceptions = db.execute(select(ExceptionRecord)).scalars().all()
    for exc in exceptions:
        leaks = find_label_leaks(exc.evidence or {})
        assert leaks == [], f"label leak in exception evidence: {leaks}"

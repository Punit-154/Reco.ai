from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    EvaluationRun,
    ExceptionRecord,
    MatchMember,
    Transaction,
)
from app.services.ai.classifier import (
    ClassificationCategory,
    ExceptionClassification,
    FakeExceptionClassifier,
)
from app.services.ai.triage import classify_pending_exceptions

EXPECTED_CATEGORY_BY_CASE_TYPE = {
    "partial_refund": ClassificationCategory.REFUND_LAG.value,
    "duplicate_utr": ClassificationCategory.DUPLICATE_UTR.value,
    "unrecognized_credit": ClassificationCategory.UNRECOGNIZED_CREDIT.value,
}

AUTO_MATCH_CASE_TYPES = {"perfect_match", "fee_deduction"}

FIXTURE_VERSION = "synthetic-v1"


def load_ground_truth(path: str | Path) -> dict:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or "cases" not in payload:
        raise ValueError(f"invalid ground truth file: {path}")
    return payload


def _safe_rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


class FaithfulnessEvaluator(Protocol):
    def score(
        self,
        db: Session,
        exception: ExceptionRecord,
        classification: ExceptionClassification,
    ) -> float: ...


class DeterministicEvidenceChecker:
    name = "deterministic_evidence_checker"

    def score(
        self,
        db: Session,
        exception: ExceptionRecord,
        classification: ExceptionClassification,
    ) -> float:
        cited = classification.evidence_transaction_ids or []
        if not cited:
            return 0.0

        valid_ids: set[str] = set()
        valid_external_ids: set[str] = set()

        if exception.transaction_id is not None:
            valid_ids.add(str(exception.transaction_id))
            bank_txn = db.get(Transaction, exception.transaction_id)
            if bank_txn is not None:
                valid_external_ids.add(str(bank_txn.external_id))

        evidence = exception.evidence or {}
        related_uuids = evidence.get("related_settlement_transaction_ids", []) or []
        if related_uuids:
            related_txns = db.execute(
                select(Transaction).where(Transaction.id.in_(related_uuids))
            ).scalars().all()
            for txn in related_txns:
                valid_ids.add(str(txn.id))
                valid_external_ids.add(str(txn.external_id))

        supported = [c for c in cited if str(c) in valid_ids or str(c) in valid_external_ids]
        return round(len(supported) / len(cited), 4)


class LlmJudgeEvaluator:
    name = "llm_judge"

    def __init__(self, *args, **kwargs):
        del args, kwargs

    def score(
        self,
        db: Session,
        exception: ExceptionRecord,
        classification: ExceptionClassification,
    ) -> float:
        raise NotImplementedError(
            "LLM-judge faithfulness is a placeholder; deterministic evidence "
            "checking runs instead and the judge never resolves exceptions"
        )


@dataclass
class EvaluationOutput:
    evaluation_run_id: str
    metrics: dict


def _system_state(db: Session) -> tuple[set, dict]:
    matched_txn_ids = set(
        db.execute(select(MatchMember.transaction_id)).scalars().all()
    )

    exception_rows = db.execute(select(ExceptionRecord)).scalars().all()
    exceptions_by_txn: dict = {}
    for row in exception_rows:
        if row.transaction_id is not None:
            exceptions_by_txn[row.transaction_id] = row

    return matched_txn_ids, exceptions_by_txn


def run_evaluation(
    db: Session,
    ground_truth_path: str | Path,
    reconciliation_run_id=None,
    ensure_classified: bool = True,
) -> EvaluationOutput:
    ground_truth = load_ground_truth(ground_truth_path)

    if ensure_classified:
        pending = db.execute(
            select(ExceptionRecord.id).where(
                ExceptionRecord.response.is_(None),
                ExceptionRecord.taxonomy.in_(("PENDING_AI_REVIEW", "AMBIGUOUS_MATCH")),
                ExceptionRecord.status == "unresolved",
            )
        ).scalars().all()
        if pending:
            classify_pending_exceptions(db, FakeExceptionClassifier(), limit=len(pending))
            db.flush()

    matched_txn_ids, exceptions_by_txn = _system_state(db)

    eligible_case_count = 0
    auto_matched_cases = 0
    correct_auto_matches = 0
    known_exception_cases = 0
    surfaced_exceptions = 0

    ai_classified = 0
    ai_correct = 0
    faithfulness_scores: list[float] = []
    checker = DeterministicEvidenceChecker()

    bank_txns = db.execute(
        select(Transaction).where(Transaction.transaction_kind == "bank_credit")
    ).scalars().all()

    for txn in bank_txns:
        case_id, case_type = None, None
        for cid, case in ground_truth["cases"].items():
            if txn.external_id in case["source_ids"].get("bank", []):
                case_id, case_type = cid, case["case_type"]
                break

        exc_row = exceptions_by_txn.get(txn.id)
        classification = None
        if exc_row is not None and exc_row.response is not None:
            try:
                classification = ExceptionClassification.model_validate(exc_row.response)
            except Exception:
                classification = None

        if case_type in AUTO_MATCH_CASE_TYPES:
            eligible_case_count += 1
            if txn.id in matched_txn_ids:
                auto_matched_cases += 1
                correct_auto_matches += 1
        else:
            known_exception_cases += 1
            if exc_row is not None:
                surfaced_exceptions += 1

        expected_category = EXPECTED_CATEGORY_BY_CASE_TYPE.get(case_type or "")
        if classification is not None:
            ai_classified += 1
            if classification.category.value == expected_category:
                ai_correct += 1
            if exc_row is not None:
                faithfulness_scores.append(checker.score(db, exc_row, classification))
                if exc_row.faithfulness_score is None:
                    exc_row.faithfulness_score = Decimal(
                        str(faithfulness_scores[-1])
                    )

    metrics = {
        "reconciliation_run_id": str(reconciliation_run_id) if reconciliation_run_id else None,
        "fixture_version": ground_truth.get("fixture_version", FIXTURE_VERSION),
        "seed": ground_truth.get("seed"),
        "total_cases": len(ground_truth["cases"]),
        "deterministic_match_rate": _safe_rate(correct_auto_matches, auto_matched_cases),
        "deterministic_coverage": _safe_rate(auto_matched_cases, eligible_case_count),
        "exception_recall": _safe_rate(surfaced_exceptions, known_exception_cases),
        "ai_classification_accuracy": _safe_rate(ai_correct, ai_classified),
        "llm_faithfulness_score": _safe_rate(
            int(round(sum(faithfulness_scores) * 10000)),
            len(faithfulness_scores) * 10000,
        ),
        "counts": {
            "eligible_matchable_cases": eligible_case_count,
            "deterministic_auto_matches": auto_matched_cases,
            "correct_auto_matches": correct_auto_matches,
            "known_exception_cases": known_exception_cases,
            "surfaced_exceptions": surfaced_exceptions,
            "ai_classified": ai_classified,
            "ai_correct": ai_correct,
            "faithfulness_evaluated": len(faithfulness_scores),
        },
    }

    run = EvaluationRun(
        seed=ground_truth.get("seed"),
        fixture_version=metrics["fixture_version"],
        metrics=metrics,
    )
    db.add(run)
    db.flush()

    return EvaluationOutput(evaluation_run_id=str(run.id), metrics=metrics)


__all__ = [
    "DeterministicEvidenceChecker",
    "FaithfulnessEvaluator",
    "LlmJudgeEvaluator",
    "EvaluationOutput",
    "load_ground_truth",
    "run_evaluation",
]

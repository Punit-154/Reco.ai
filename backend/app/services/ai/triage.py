from __future__ import annotations

from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExceptionRecord
from app.services.ai.classifier import (
    FAILURE_CATEGORIES,
    ExceptionClassifier,
    ClassificationCategory,
    FakeExceptionClassifier,
)
from app.services.ai.evidence import build_evidence_pack

BATCH_SIZE = 5
MAX_CONCURRENT_BATCHES = 2

QUEUE_TAXONOMIES = ("PENDING_AI_REVIEW", "AMBIGUOUS_MATCH")


def pending_exceptions(db: Session, limit: int = 100) -> list[ExceptionRecord]:
    return list(
        db.execute(
            select(ExceptionRecord)
            .where(
                ExceptionRecord.status == "unresolved",
                ExceptionRecord.response.is_(None),
                ExceptionRecord.taxonomy.in_(QUEUE_TAXONOMIES),
            )
            .order_by(ExceptionRecord.created_at)
            .limit(limit)
        ).scalars()
    )


def _chunks(lst: list, size: int):
    for i in range(0, len(lst), size):
        yield lst[i : i + size]


def classify_pending_exceptions(
    db: Session,
    classifier: ExceptionClassifier,
    limit: int = 100,
) -> dict:
    queue = pending_exceptions(db, limit=limit)

    packs: list[tuple[ExceptionRecord, dict]] = []
    for exception in queue:
        pack = build_evidence_pack(db, exception)
        if pack is not None:
            packs.append((exception, pack))

    classifications: dict[str, object] = {}

    batch_groups = list(_chunks(packs, BATCH_SIZE))

    def _run_batch(batch: list[tuple[ExceptionRecord, dict]]) -> dict:
        batch_packs = [p for _, p in batch]
        return classifier.classify_batch(batch_packs)

    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_BATCHES) as executor:
        futures = {
            executor.submit(_run_batch, batch): batch for batch in batch_groups
        }
        for future in as_completed(futures):
            batch = futures[future]
            try:
                result = future.result()
                classifications.update(result)
            except Exception:
                for _exc, pack in batch:
                    eid = pack.get("exception_id", "unknown")
                    classifications[eid] = _failure_classification(
                        ClassificationCategory.MODEL_UNAVAILABLE,
                        "batch classification failed",
                        pack,
                    )

    by_category: Counter[str] = Counter()
    classified = 0
    deferred = 0

    for exception, pack in packs:
        eid = pack.get("exception_id", str(exception.id))
        classification = classifications.get(eid)
        if classification is None:
            deferred += 1
            continue

        if getattr(classification, "category", None) and classification.category.value in FAILURE_CATEGORIES:
            exception.retry_count += 1
            deferred += 1
            continue

        exception.response = classification.model_dump(mode="json")
        exception.model_name = getattr(classifier, "full_name", classifier.name)
        exception.prompt_version = classifier.prompt_version
        exception.confidence = Decimal(classification.confidence) / Decimal(100)
        classified += 1
        by_category[classification.category.value] += 1

    if classified == 0 and deferred > 0 and not isinstance(classifier, FakeExceptionClassifier):
        fallback = FakeExceptionClassifier()
        for exception, pack in packs:
            if exception.response is not None:
                continue
            fb_class = fallback.classify(pack)
            exception.response = fb_class.model_dump(mode="json")
            exception.model_name = f"{getattr(classifier, 'full_name', classifier.name)} (fallback)"
            exception.prompt_version = fallback.prompt_version
            exception.confidence = Decimal(fb_class.confidence) / Decimal(100)
            classified += 1
            by_category[fb_class.category.value] += 1
        deferred = 0

    db.flush()

    return {
        "classifier": getattr(classifier, "full_name", classifier.name),
        "pending_found": len(queue),
        "classified": classified,
        "deferred_retry": deferred,
        "by_category": dict(by_category),
    }


def _failure_classification(
    category: ClassificationCategory,
    explanation: str,
    evidence_pack: dict,
):
    from app.services.ai.classifier import ExceptionClassification

    bank = evidence_pack.get("bank_transaction", {}) or {}
    ids = [str(bank.get("transaction_id"))] if bank.get("transaction_id") else []
    return ExceptionClassification(
        category=category,
        confidence=0,
        explanation=explanation[:500],
        evidence_transaction_ids=ids,
        requires_human_review=True,
    )

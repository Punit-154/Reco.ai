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
)
from app.services.ai.evidence import build_evidence_pack

MAX_CONCURRENCY = 3

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

    classifications: dict = {}
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as executor:
        futures = {
            executor.submit(classifier.classify, pack): exception
            for exception, pack in packs
        }
        for future in as_completed(futures):
            exception = futures[future]
            classifications[exception.id] = future.result()

    by_category: Counter[str] = Counter()
    classified = 0
    deferred = 0

    for exception, _pack in packs:
        classification = classifications[exception.id]
        if classification.category.value in FAILURE_CATEGORIES:
            exception.retry_count += 1
            deferred += 1
            continue

        exception.response = classification.model_dump(mode="json")
        exception.model_name = getattr(classifier, "full_name", classifier.name)
        exception.prompt_version = classifier.prompt_version
        exception.confidence = Decimal(classification.confidence) / Decimal(100)
        classified += 1
        by_category[classification.category.value] += 1

    db.flush()

    return {
        "classifier": getattr(classifier, "full_name", classifier.name),
        "pending_found": len(queue),
        "classified": classified,
        "deferred_retry": deferred,
        "by_category": dict(by_category),
    }

import csv
import io
import uuid

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AuditLog, ExceptionRecord, Transaction
from ..schemas.classification import ClassifyPendingRequest
from ..services.ai.classifier import ClassificationCategory, get_classifier
from ..services.ai.triage import classify_pending_exceptions

router = APIRouter(prefix="/api/exceptions", tags=["exceptions"])

FINAL_STATUSES = {"approved", "rejected", "overridden"}

STATUS_BY_ACTION = {
    "approve": "approved",
    "reject": "rejected",
    "manual_override": "overridden",
}


def _serialize(row: ExceptionRecord, db: Session | None = None) -> dict:
    result = {
        "id": str(row.id),
        "status": row.status,
        "taxonomy": row.taxonomy,
        "confidence": float(row.confidence) if row.confidence is not None else None,
        "model_name": row.model_name,
        "prompt_version": row.prompt_version,
        "response": row.response,
        "evidence": row.evidence,
        "faithfulness_score": (
            float(row.faithfulness_score) if row.faithfulness_score is not None else None
        ),
        "retry_count": row.retry_count,
    }

    response = row.response or {}
    evidence_ids = response.get("evidence_transaction_ids") or []
    if evidence_ids and db is not None:
        import uuid as _uuid

        uuid_vals = []
        external_ids = []
        for eid in evidence_ids:
            try:
                uuid_vals.append(_uuid.UUID(eid))
            except (ValueError, TypeError):
                external_ids.append(eid)

        txn_map: dict = {}
        if uuid_vals:
            txns = db.execute(
                select(Transaction).where(Transaction.id.in_(uuid_vals))
            ).scalars().all()
            for t in txns:
                txn_map[str(t.id)] = t
        if external_ids:
            txns = db.execute(
                select(Transaction).where(Transaction.external_id.in_(external_ids))
            ).scalars().all()
            for t in txns:
                txn_map[t.external_id] = t

        result["resolved_evidence"] = [
            {
                "id": eid,
                "external_id": txn_map[eid].external_id if eid in txn_map else eid,
                "amount_paise": txn_map[eid].amount_paise if eid in txn_map else None,
                "kind": txn_map[eid].transaction_kind if eid in txn_map else None,
                "effective_date": txn_map[eid].effective_date.isoformat() if eid in txn_map else None,
            }
            for eid in evidence_ids
        ]
    else:
        result["resolved_evidence"] = []

    return result


@router.get("")
def list_exceptions(db: Session = Depends(get_db)):
    rows = db.execute(
        select(ExceptionRecord).order_by(ExceptionRecord.created_at).limit(500)
    ).scalars().all()
    return [_serialize(r, db) for r in rows]


@router.post("/classify-pending")
def classify_pending(
    payload: ClassifyPendingRequest | None = None,
    db: Session = Depends(get_db),
    settings=Depends(get_settings),
):
    request = payload or ClassifyPendingRequest()
    try:
        classifier = get_classifier(settings, use_ai=request.use_ai)
        result = classify_pending_exceptions(db, classifier, limit=request.limit)
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"classification failed: {exc}") from exc
    return result


@router.get("/categories")
def list_categories():
    return [c.value for c in ClassificationCategory]


@router.get("/audit-logs")
def list_audit_logs(
    entity_type: str | None = None,
    entity_id: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
):
    limit = max(1, min(limit, 200))
    query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if entity_type:
        query = query.where(AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.where(AuditLog.entity_id == entity_id)

    logs = db.execute(query).scalars().all()
    return [
        {
            "id": str(log.id),
            "action": log.action,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "previous_state": log.previous_state,
            "new_state": log.new_state,
            "ai_hypothesis": log.ai_hypothesis,
            "reason": log.reason,
            "created_at": log.created_at.isoformat(),
        }
        for log in logs
    ]


CSV_COLUMNS = [
    "id", "status", "taxonomy", "confidence", "model_name",
    "bank_external_id", "bank_amount_paise", "bank_currency", "bank_effective_date",
    "normalized_utr", "reason_code", "ai_category", "ai_confidence", "ai_explanation",
    "faithfulness_score", "retry_count",
]


@router.get("/export/csv")
def export_exceptions_csv(db: Session = Depends(get_db)):
    rows = db.execute(
        select(ExceptionRecord).order_by(ExceptionRecord.created_at)
    ).scalars().all()

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=CSV_COLUMNS)
    writer.writeheader()

    for row in rows:
        evidence = row.evidence or {}
        response = row.response or {}
        writer.writerow({
            "id": str(row.id),
            "status": row.status,
            "taxonomy": row.taxonomy,
            "confidence": float(row.confidence) if row.confidence is not None else "",
            "model_name": row.model_name or "",
            "bank_external_id": evidence.get("bank_external_id", ""),
            "bank_amount_paise": evidence.get("bank_amount_paise", ""),
            "bank_currency": evidence.get("bank_currency", ""),
            "bank_effective_date": evidence.get("bank_effective_date", ""),
            "normalized_utr": evidence.get("normalized_utr", ""),
            "reason_code": evidence.get("reason_code", ""),
            "ai_category": response.get("category", ""),
            "ai_confidence": response.get("confidence", ""),
            "ai_explanation": response.get("explanation", ""),
            "faithfulness_score": float(row.faithfulness_score) if row.faithfulness_score is not None else "",
            "retry_count": row.retry_count,
        })

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=exception_list.csv"},
    )


RUNTIME_TABLES = (
    "audit_logs, match_members, exceptions, transactions, ingestion_runs, "
    "webhook_events, match_groups, sources, reconciliation_runs, evaluation_runs"
)


@router.delete("")
def clear_all_exceptions(db: Session = Depends(get_db)):
    try:
        db.execute(text(f"TRUNCATE TABLE {RUNTIME_TABLES} RESTART IDENTITY CASCADE"))
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"clear failed: {exc}") from exc
    return {"cleared": True, "tables_truncated": len(RUNTIME_TABLES.split(","))}


@router.get("/{exception_id}")
def get_exception(exception_id: str, db: Session = Depends(get_db)):
    try:
        parsed = uuid.UUID(exception_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="exception_id must be a UUID") from exc
    row = db.get(ExceptionRecord, parsed)
    if row is None:
        raise HTTPException(status_code=404, detail="exception not found")
    return _serialize(row, db)


@router.post("/{exception_id}/decision")
def decide_exception(
    exception_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    settings=Depends(get_settings),
):
    from ..schemas.decision import DecisionRequest

    try:
        body = DecisionRequest.model_validate(payload)
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        parsed = uuid.UUID(exception_id)
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="exception_id must be a UUID") from exc

    row = db.get(ExceptionRecord, parsed)
    if row is None:
        db.rollback()
        raise HTTPException(status_code=404, detail="exception not found")

    if row.status in FINAL_STATUSES:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"exception already decided ({row.status}); no reopening in demo mode",
        )

    override_category = None
    if body.override_category is not None:
        try:
            override_category = ClassificationCategory(body.override_category).value
        except ValueError as exc:
            db.rollback()
            raise HTTPException(
                status_code=422,
                detail=f"override_category must be one of {[c.value for c in ClassificationCategory]}",
            ) from exc

    previous_state = {
        "status": row.status,
        "taxonomy": row.taxonomy,
        "confidence": float(row.confidence) if row.confidence is not None else None,
    }
    new_status = STATUS_BY_ACTION[body.action.value]
    new_state = {
        "status": new_status,
        "taxonomy": override_category or row.taxonomy,
        "override_category": override_category,
    }

    actor_uuid = uuid.UUID(settings.demo_actor_uuid)
    audit = AuditLog(
        actor_id=actor_uuid,
        action=f"exception_{body.action.value}",
        entity_type="exception",
        entity_id=str(row.id),
        previous_state=previous_state,
        new_state=new_state,
        ai_hypothesis=row.response,
        reason=body.reason,
    )
    db.add(audit)

    row.status = new_status
    if override_category is not None:
        row.taxonomy = override_category

    try:
        db.flush()
        db.refresh(audit)
        response_exception = _serialize(row)
        response_audit = {
            "id": str(audit.id),
            "action": audit.action,
            "entity_type": audit.entity_type,
            "entity_id": audit.entity_id,
            "previous_state": audit.previous_state,
            "new_state": audit.new_state,
            "ai_hypothesis": audit.ai_hypothesis,
            "reason": audit.reason,
            "created_at": audit.created_at.isoformat(),
        }
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail="decision failed") from exc

    return {"exception": response_exception, "audit_event": response_audit}

from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings, get_settings
from ..db import get_db
from ..models import WebhookEvent
from ..services.ingestion.importers import ingest_razorpay_items
from ..services.webhooks.razorpay import (
    SETTLEMENT_PROCESSED_EVENT,
    validate_razorpay_webhook,
    WebhookValidationError,
)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


def _load_payload(raw_body: bytes) -> tuple[dict, str]:
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"unparseable_body": raw_body.decode("utf-8", errors="replace")}, "unknown"
    if not isinstance(payload, dict):
        return {"unparseable_body": raw_body.decode("utf-8", errors="replace")}, "unknown"
    event_type = str(payload.get("event") or "unknown")
    return payload, event_type


@router.post("/razorpay")
async def razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    try:
        raw_body = await validate_razorpay_webhook(request, settings.razorpay_webhook_secret)
    except WebhookValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    event_id = request.headers.get("x-razorpay-event-id", "").strip()
    if not event_id:
        raise HTTPException(status_code=400, detail="missing x-razorpay-event-id header")

    existing = db.execute(
        select(WebhookEvent.id).where(WebhookEvent.provider_event_id == event_id)
    ).scalar_one_or_none()
    if existing is not None:
        return {
            "status": "skipped",
            "reason": "duplicate_event",
            "event_id": event_id,
        }

    payload, event_type = _load_payload(raw_body)

    event = WebhookEvent(
        provider_event_id=event_id,
        event_type=event_type,
        signature_valid=True,
        raw_payload=payload,
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {
            "status": "skipped",
            "reason": "duplicate_event",
            "event_id": event_id,
        }
    db.commit()

    if event_type != SETTLEMENT_PROCESSED_EVENT:
        return {
            "status": "ignored",
            "reason": "unsupported_event_type",
            "event_type": event_type,
            "event_id": event_id,
        }

    try:
        entity = payload["payload"]["settlement"]["entity"]
        summary = ingest_razorpay_items(db, [entity], file_name=f"webhook:{event_id}")
        if summary.failed_rows > 0:
            db.rollback()
            return {
                "status": "accepted",
                "processing": "failed",
                "detail": f"{summary.failed_rows} settlement row(s) rejected during normalization",
                "errors": [e.model_dump() for e in summary.errors],
                "event_id": event_id,
            }
        db.commit()
    except Exception as exc:
        db.rollback()
        return {
            "status": "accepted",
            "processing": "failed",
            "detail": str(exc),
            "event_id": event_id,
        }

    event.processed_at = datetime.now(timezone.utc)
    db.commit()

    return {
        "status": "processed",
        "event_id": event_id,
        "transaction_created": summary.inserted > 0,
        "duplicate_transaction": summary.skipped_duplicates > 0,
    }

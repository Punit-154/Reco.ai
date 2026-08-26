from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ExceptionRecord, Transaction


def _transaction_facts(txn: Transaction) -> dict:
    return {
        "transaction_id": str(txn.id),
        "external_id": txn.external_id,
        "kind": txn.transaction_kind,
        "amount_paise": int(txn.amount_paise),
        "gross_amount_paise": txn.gross_amount_paise,
        "fee_paise": txn.fee_paise,
        "tax_paise": txn.tax_paise,
        "refund_amount_paise": txn.refund_amount_paise,
        "currency": txn.currency,
        "effective_date": txn.effective_date.isoformat(),
        "normalized_utr": (txn.utr or "").strip().upper() or None,
    }


def build_evidence_pack(db: Session, exception: ExceptionRecord) -> dict | None:
    if exception.transaction_id is None:
        return None
    bank = db.get(Transaction, exception.transaction_id)
    if bank is None:
        return None

    evidence = exception.evidence or {}
    related_ids = []
    for raw_id in evidence.get("related_settlement_transaction_ids", []) or []:
        try:
            related_ids.append(uuid.UUID(str(raw_id)))
        except ValueError:
            continue

    settlements = (
        db.execute(select(Transaction).where(Transaction.id.in_(related_ids))).scalars().all()
        if related_ids
        else []
    )

    settlement_facts = [_transaction_facts(s) for s in settlements]
    candidate_deltas = [
        {
            "settlement_external_id": s["external_id"],
            "delta_paise": s["amount_paise"] - int(bank.amount_paise),
        }
        for s in settlement_facts
    ]

    return {
        "exception_id": str(exception.id),
        "reason_code": evidence.get("reason_code"),
        "deterministic_explanation": evidence.get("explanation"),
        "bank_transaction": _transaction_facts(bank),
        "related_settlements": settlement_facts,
        "candidate_deltas": candidate_deltas,
    }

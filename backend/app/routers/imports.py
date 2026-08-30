import csv
import io
import random
from datetime import date, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import DEMO_ORG_ID, get_settings
from ..db import get_db
from ..models import Source, Transaction
from ..services.ingestion.importers import (
    FatalImportError,
    ingest_bank_csv,
    ingest_ledger_csv,
    ingest_razorpay_items,
    ingest_razorpay_settlements,
)
from ..services.razorpay.polling import HttpSettlementsPoller

router = APIRouter(prefix="/api/imports", tags=["imports"])


async def _read_upload(file: UploadFile) -> tuple[bytes, str]:
    content = await file.read()
    name = file.filename or "upload"
    return content, name


@router.get("/sources")
def list_sources(db: Session = Depends(get_db)):
    org_id = DEMO_ORG_ID
    rows = db.execute(
        select(
            Source.kind,
            Source.name,
            func.count(Transaction.id).label("txn_count"),
        )
        .outerjoin(Transaction, Transaction.source_id == Source.id)
        .where(Source.org_id == org_id)
        .group_by(Source.kind, Source.name)
        .order_by(Source.kind)
    ).all()
    return [
        {"kind": r.kind, "name": r.name, "txn_count": r.txn_count}
        for r in rows
    ]


@router.post("/bank")
async def import_bank(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    content, name = await _read_upload(file)
    try:
        summary = ingest_bank_csv(db, content, file_name=name)
        db.commit()
    except FatalImportError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return summary


@router.post("/ledger")
async def import_ledger(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    content, name = await _read_upload(file)
    try:
        summary = ingest_ledger_csv(db, content, file_name=name)
        db.commit()
    except FatalImportError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return summary


@router.post("/razorpay-settlements")
async def import_razorpay_settlements(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    content, name = await _read_upload(file)
    try:
        summary = ingest_razorpay_settlements(db, content, file_name=name)
        db.commit()
    except FatalImportError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return summary


@router.post("/razorpay-live")
def fetch_razorpay_live(
    db: Session = Depends(get_db),
    settings=Depends(get_settings),
):
    try:
        poller = HttpSettlementsPoller(settings.razorpay_key_id, settings.razorpay_key_secret)
        items = poller.fetch_settlements()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Razorpay API error: {exc}") from exc

    if not items:
        return {"inserted": 0, "skipped_duplicates": 0, "failed_rows": 0, "errors": [], "settlements": [], "count": 0}

    try:
        summary = ingest_razorpay_items(db, items, file_name="razorpay_api_live")
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"ingestion failed: {exc}") from exc

    return {
        "ingestion": summary,
        "settlements": items,
        "count": len(items),
    }


@router.post("/generate-sample")
def generate_sample_data(
    db: Session = Depends(get_db),
):
    settlements = db.execute(
        select(Transaction)
        .where(Transaction.transaction_kind == "settlement")
        .order_by(Transaction.effective_date)
    ).scalars().all()

    if not settlements:
        raise HTTPException(
            status_code=400,
            detail="No settlements found. Fetch from Razorpay API first.",
        )

    bank_rows = []
    ledger_rows = []
    random.seed(42)

    for i, txn in enumerate(settlements):
        utr = txn.utr or f"UTR{i:04d}"
        amount_str = f"{txn.amount_paise / 100:.2f}"
        fee_str = f"{(txn.fee_paise or 0) / 100:.2f}"
        tax_str = f"{(txn.tax_paise or 0) / 100:.2f}"
        gross_str = f"{(txn.gross_amount_paise or txn.amount_paise) / 100:.2f}"
        net_str = amount_str

        bank_rows.append({
            "txn_ref": f"BNK{random.randint(100000, 999999):06d}",
            "value_date": txn.effective_date.isoformat(),
            "description": f"NEFT CR {utr} RAZORPAY SETTLEMENT",
            "credit_amount_inr": net_str,
            "currency": txn.currency or "INR",
        })

        ledger_rows.append({
            "ledger_entry_id": f"LDG{i + 1:04d}",
            "invoice_ref": f"INV-{random.randint(100000, 999999):06d}",
            "posted_date": txn.effective_date.isoformat(),
            "gross_amount_inr": gross_str,
            "fee_amount_inr": fee_str,
            "tax_amount_inr": tax_str,
            "refund_amount_inr": "0.00",
            "currency": txn.currency or "INR",
            "narration": f"RAZORPAY SETTLEMENT {utr}",
        })

    bank_buf = io.StringIO()
    bank_writer = csv.DictWriter(bank_buf, fieldnames=["txn_ref", "value_date", "description", "credit_amount_inr", "currency"])
    bank_writer.writeheader()
    bank_writer.writerows(bank_rows)

    ledger_buf = io.StringIO()
    ledger_writer = csv.DictWriter(ledger_buf, fieldnames=["ledger_entry_id", "invoice_ref", "posted_date", "gross_amount_inr", "fee_amount_inr", "tax_amount_inr", "refund_amount_inr", "currency", "narration"])
    ledger_writer.writeheader()
    ledger_writer.writerows(ledger_rows)

    try:
        bank_summary = ingest_bank_csv(db, bank_buf.getvalue().encode("utf-8"), file_name="sample_bank_from_razorpay.csv")
        ledger_summary = ingest_ledger_csv(db, ledger_buf.getvalue().encode("utf-8"), file_name="sample_ledger_from_razorpay.csv")
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"sample data ingestion failed: {exc}") from exc

    return {
        "bank": bank_summary,
        "ledger": ledger_summary,
        "bank_rows": len(bank_rows),
        "ledger_rows": len(ledger_rows),
    }

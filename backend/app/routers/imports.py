from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import DEMO_ORG_ID
from ..db import get_db
from ..models import Source, Transaction
from ..services.ingestion.importers import (
    FatalImportError,
    ingest_bank_csv,
    ingest_ledger_csv,
    ingest_razorpay_settlements,
)

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

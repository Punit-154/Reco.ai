from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..db import get_db
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

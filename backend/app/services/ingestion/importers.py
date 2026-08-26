from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DEMO_ORG_ID
from app.contracts.razorpay import RazorpaySettlement
from app.models import IngestionRun, Source, Transaction
from app.schemas.ingestion import IngestionSummary, RowError

from .money import parse_rupees_to_paise

NORMALIZATION_VERSION = "v1"

SOURCE_KINDS = {
    "bank": ("bank_statement", "bank_statement"),
    "ledger": ("ledger", "ledger"),
    "razorpay_settlements": ("razorpay_settlements", "razorpay_settlements"),
}

UTR_PATTERN = re.compile(r"\b([A-Z]{4}[0-9]{9,12})\b")

BANK_REQUIRED_COLUMNS = ("txn_ref", "value_date", "credit_amount_inr", "currency")
LEDGER_REQUIRED_COLUMNS = ("ledger_entry_id", "posted_date", "gross_amount_inr", "currency")


class FatalImportError(Exception):
    pass


@dataclass
class _ParsedRow:
    external_id: str
    transaction_kind: str
    direction: str = "credit"
    amount_paise: int = 0
    gross_amount_paise: int | None = None
    fee_paise: int | None = None
    tax_paise: int | None = None
    refund_amount_paise: int | None = None
    currency: str = "INR"
    effective_date: date | None = None
    posted_at: datetime | None = None
    utr: str | None = None
    reference_id: str | None = None
    narration: str | None = None
    raw_payload: dict = field(default_factory=dict)


def get_or_create_source(db: Session, kind: str) -> Source:
    source_kind, source_name = SOURCE_KINDS[kind]
    org_id = uuid.UUID(DEMO_ORG_ID)
    source = db.execute(
        select(Source).where(
            Source.org_id == org_id,
            Source.kind == source_kind,
            Source.name == source_name,
        )
    ).scalar_one_or_none()
    if source is None:
        source = Source(org_id=org_id, kind=source_kind, name=source_name)
        db.add(source)
        db.flush()
    return source


def _decode(content_bytes: bytes) -> str:
    try:
        return content_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise FatalImportError(f"file must be UTF-8 encoded: {exc}") from exc


def _require_columns(row: dict, required: tuple[str, ...], row_number: int) -> None:
    for column in required:
        value = row.get(column)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise ValueError(f"missing required field '{column}'")


def _parse_currency(value: str) -> str:
    currency = (value or "").strip().upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError(f"invalid currency '{value}'")
    return currency


def _parse_iso_date(value: str, field_name: str) -> date:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError as exc:
        raise ValueError(f"invalid {field_name} '{value}'") from exc


def _normalize_bank_row(row: dict, row_number: int) -> _ParsedRow:
    _require_columns(row, BANK_REQUIRED_COLUMNS, row_number)
    amount_paise = parse_rupees_to_paise(row["credit_amount_inr"])
    if amount_paise <= 0:
        raise ValueError("credit amount must be positive")
    description = (row.get("description") or "").strip()
    match = UTR_PATTERN.search(description.upper())
    return _ParsedRow(
        external_id=row["txn_ref"].strip(),
        transaction_kind="bank_credit",
        amount_paise=amount_paise,
        gross_amount_paise=amount_paise,
        currency=_parse_currency(row["currency"]),
        effective_date=_parse_iso_date(row["value_date"], "value_date"),
        utr=match.group(1) if match else None,
        narration=description or None,
        raw_payload={k: (v if v is not None else "") for k, v in row.items()},
    )


def _normalize_ledger_row(row: dict, row_number: int) -> _ParsedRow:
    _require_columns(row, LEDGER_REQUIRED_COLUMNS, row_number)
    gross = parse_rupees_to_paise(row["gross_amount_inr"])
    fee = parse_rupees_to_paise(row.get("fee_amount_inr") or "0")
    tax = parse_rupees_to_paise(row.get("tax_amount_inr") or "0")
    refund = parse_rupees_to_paise(row.get("refund_amount_inr") or "0")
    if gross < 0 or fee < 0 or tax < 0 or refund < 0:
        raise ValueError("ledger amounts must not be negative")
    net = gross - fee - tax - refund
    narration = (row.get("narration") or "").strip()
    invoice_ref = (row.get("invoice_ref") or "").strip() or None
    return _ParsedRow(
        external_id=row["ledger_entry_id"].strip(),
        transaction_kind="ledger_entry",
        amount_paise=net,
        gross_amount_paise=gross,
        fee_paise=fee,
        tax_paise=tax,
        refund_amount_paise=refund,
        currency=_parse_currency(row["currency"]),
        effective_date=_parse_iso_date(row["posted_date"], "posted_date"),
        reference_id=invoice_ref,
        narration=narration or None,
        raw_payload={k: (v if v is not None else "") for k, v in row.items()},
    )


def _normalize_razorpay_item(item: dict, row_number: int) -> _ParsedRow:
    settlement = RazorpaySettlement.model_validate(item)
    created_at = datetime.fromtimestamp(settlement.created_at, tz=timezone.utc)
    return _ParsedRow(
        external_id=settlement.id,
        transaction_kind="settlement",
        amount_paise=settlement.amount,
        gross_amount_paise=settlement.amount,
        fee_paise=settlement.fees,
        tax_paise=settlement.tax,
        currency=str(item.get("currency", "INR")).upper(),
        effective_date=created_at.date(),
        posted_at=created_at,
        utr=settlement.utr,
        raw_payload=dict(item),
    )


def _parse_csv_rows(content_bytes: bytes, required_columns: tuple[str, ...]) -> list[dict]:
    import csv
    import io

    text = _decode(content_bytes)
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise FatalImportError("CSV file has no header row")
    missing = [c for c in required_columns if c not in reader.fieldnames]
    if missing:
        raise FatalImportError(f"missing required columns: {', '.join(missing)}")
    return [
        {(k or ""): (v if v is not None else "") for k, v in row.items()}
        for row in reader
    ]


def ingest_bank_csv(db: Session, content_bytes: bytes, file_name: str = "bank_statement.csv") -> IngestionSummary:
    rows = _parse_csv_rows(content_bytes, BANK_REQUIRED_COLUMNS)
    return _run_ingest(
        db,
        kind="bank",
        file_name=file_name,
        content_bytes=content_bytes,
        rows=list(enumerate(rows, start=2)),
        normalize=_normalize_bank_row,
    )


def ingest_ledger_csv(db: Session, content_bytes: bytes, file_name: str = "ledger.csv") -> IngestionSummary:
    rows = _parse_csv_rows(content_bytes, LEDGER_REQUIRED_COLUMNS)
    return _run_ingest(
        db,
        kind="ledger",
        file_name=file_name,
        content_bytes=content_bytes,
        rows=list(enumerate(rows, start=2)),
        normalize=_normalize_ledger_row,
    )


def ingest_razorpay_settlements(db: Session, content_bytes: bytes, file_name: str = "razorpay_settlements.json") -> IngestionSummary:
    try:
        payload = json.loads(_decode(content_bytes))
    except json.JSONDecodeError as exc:
        raise FatalImportError(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise FatalImportError("expected a JSON object with an 'items' array")
    items = payload.get("items")
    if not isinstance(items, list):
        raise FatalImportError("'items' must be a JSON array of settlement objects")
    return ingest_razorpay_items(db, items, file_name=file_name)


def ingest_razorpay_items(db: Session, items: list, file_name: str) -> IngestionSummary:
    return _run_ingest(
        db,
        kind="razorpay_settlements",
        file_name=file_name,
        content_bytes=json.dumps(items, separators=(",", ":")).encode("utf-8"),
        rows=list(enumerate(items, start=1)),
        normalize=_normalize_razorpay_item,
    )


def _run_ingest(
    db: Session,
    *,
    kind: str,
    file_name: str,
    content_bytes: bytes,
    rows,
    normalize,
) -> IngestionSummary:
    source = get_or_create_source(db, kind)
    run = IngestionRun(
        source_id=source.id,
        file_name=file_name,
        file_hash=hashlib.sha256(content_bytes).hexdigest(),
        status="in_progress",
    )
    db.add(run)
    db.flush()

    existing = set(
        db.execute(select(Transaction.external_id).where(Transaction.source_id == source.id)).scalars()
    )

    seen_this_run: set[str] = set()
    pending: list[Transaction] = []
    errors: list[RowError] = []
    skipped = 0

    for row_number, row in rows:
        try:
            if not isinstance(row, dict):
                raise ValueError("row must be a mapping of fields")
            parsed = normalize(row, row_number)
        except Exception as exc:
            errors.append(RowError(row_number=row_number, error=str(exc)))
            continue

        if parsed.external_id in existing or parsed.external_id in seen_this_run:
            skipped += 1
            continue
        seen_this_run.add(parsed.external_id)

        pending.append(
            Transaction(
                org_id=source.org_id,
                source_id=source.id,
                ingestion_run_id=run.id,
                normalization_version=NORMALIZATION_VERSION,
                **asdict(parsed),
            )
        )

    db.add_all(pending)
    db.flush()

    run.status = "completed_with_errors" if errors else "completed"
    run.accepted_count = len(pending)
    run.rejected_count = len(errors)
    run.error_summary = {"errors": [e.model_dump() for e in errors[:100]]}

    return IngestionSummary(
        ingestion_run_id=run.id,
        source_id=source.id,
        source_kind=source.kind,
        inserted=len(pending),
        skipped_duplicates=skipped,
        failed_rows=len(errors),
        errors=errors[:50],
    )

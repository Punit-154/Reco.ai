import io
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Source, Transaction
from app.services.evaluation.synthetic_generator import find_label_leaks
from app.services.ingestion.importers import SOURCE_KINDS
from app.services.ingestion.money import parse_rupees_to_paise

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "fixtures" / "synthetic"


def _post_csv(client, path: str, name: str, content: bytes, mimetype="text/csv"):
    return client.post(path, files={"file": (name, content, mimetype)})


@pytest.fixture(scope="module")
def bank_content() -> bytes:
    return (FIXTURES_DIR / "bank_statement.csv").read_bytes()


@pytest.fixture(scope="module")
def ledger_content() -> bytes:
    return (FIXTURES_DIR / "ledger.csv").read_bytes()


@pytest.fixture(scope="module")
def settlements_content() -> bytes:
    return (FIXTURES_DIR / "razorpay_settlements.json").read_bytes()


@pytest.mark.usefixtures("clean_tables")
def test_ingest_generated_bank_csv(client, session_factory, bank_content):
    response = _post_csv(client, "/api/imports/bank", "bank_statement.csv", bank_content)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["inserted"] == 100
    assert body["skipped_duplicates"] == 0
    assert body["failed_rows"] == 0
    assert body["source_kind"] == "bank_statement"

    with session_factory() as db:
        txns = db.execute(
            select(Transaction).where(Transaction.transaction_kind == "bank_credit")
        ).scalars().all()
        assert len(txns) == 100
        for txn in txns:
            assert isinstance(txn.amount_paise, int)
            assert txn.direction == "credit"
            assert txn.currency == "INR"
            assert txn.utr is not None or "CREDIT REF" in (txn.narration or "")


@pytest.mark.usefixtures("clean_tables")
def test_bank_utr_extracted_and_money_decimal_safe(client, session_factory, bank_content):
    import csv as csv_mod

    text = bank_content.decode("utf-8")
    rows = list(csv_mod.DictReader(io.StringIO(text)))
    response = _post_csv(client, "/api/imports/bank", "bank_statement.csv", bank_content)
    assert response.status_code == 200

    with session_factory() as db:
        txn = db.execute(
            select(Transaction).where(Transaction.external_id == rows[0]["txn_ref"])
        ).scalar_one()
        assert txn.amount_paise == parse_rupees_to_paise(rows[0]["credit_amount_inr"])
        expected_utr = rows[0]["description"].replace("NEFT CR-", "").strip()
        if "CR-" in rows[0]["description"]:
            assert txn.utr == expected_utr


@pytest.mark.usefixtures("clean_tables")
def test_ingest_generated_ledger_csv(client, session_factory, ledger_content):
    response = _post_csv(client, "/api/imports/ledger", "ledger.csv", ledger_content)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["inserted"] == 90
    assert body["failed_rows"] == 0

    with session_factory() as db:
        txns = db.execute(
            select(Transaction).where(Transaction.transaction_kind == "ledger_entry")
        ).scalars().all()
        assert len(txns) == 90
        for txn in txns:
            expected_net = (
                txn.gross_amount_paise - txn.fee_paise - txn.tax_paise - txn.refund_amount_paise
            )
            assert txn.amount_paise == expected_net
            assert all(isinstance(v, int) for v in (
                txn.gross_amount_paise, txn.fee_paise, txn.tax_paise, txn.refund_amount_paise,
            ))


@pytest.mark.usefixtures("clean_tables")
def test_ingest_generated_razorpay_settlements_json(client, session_factory, settlements_content):
    payload = json.loads(settlements_content)
    response = _post_csv(
        client,
        "/api/imports/razorpay-settlements",
        "razorpay_settlements.json",
        settlements_content,
        mimetype="application/json",
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["inserted"] == 95
    assert body["failed_rows"] == 0

    with session_factory() as db:
        txns = db.execute(
            select(Transaction).where(Transaction.transaction_kind == "settlement")
        ).scalars().all()
        assert len(txns) == len(payload["items"])
        by_external = {t.external_id: t for t in txns}
        for item in payload["items"]:
            txn = by_external[item["id"]]
            assert txn.amount_paise == item["amount"]
            assert txn.fee_paise == item["fees"]
            assert txn.tax_paise == item["tax"]
            assert txn.utr == item["utr"]
            assert txn.posted_at is not None
            assert txn.posted_at.date() == txn.effective_date


@pytest.mark.usefixtures("clean_tables")
def test_duplicate_reingestion_skips_existing_rows(client, bank_content, ledger_content, settlements_content):
    first = _post_csv(client, "/api/imports/bank", "bank_statement.csv", bank_content)
    assert first.json()["inserted"] == 100
    second = _post_csv(client, "/api/imports/bank", "bank_statement.csv", bank_content)
    assert second.status_code == 200
    body = second.json()
    assert body["inserted"] == 0
    assert body["skipped_duplicates"] == 100
    assert body["failed_rows"] == 0
    assert body["source_id"] == first.json()["source_id"]

    mixed_dupes = b"txn_ref,value_date,description,credit_amount_inr,currency\nBNKA,2026-07-01,x,10.00,INR\nBNKA,2026-07-02,x,10.00,INR\n"
    r1 = _post_csv(client, "/api/imports/bank", "b.csv", mixed_dupes)
    r2 = _post_csv(client, "/api/imports/bank", "b.csv", mixed_dupes)
    assert r1.json()["inserted"] == 1 and r1.json()["skipped_duplicates"] == 1
    assert r2.json()["inserted"] == 0 and r2.json()["skipped_duplicates"] == 2


@pytest.mark.usefixtures("clean_tables")
def test_source_names_and_types_are_stable(client, bank_content, ledger_content, settlements_content):
    r1 = _post_csv(client, "/api/imports/bank", "a.csv", bank_content).json()
    r2 = _post_csv(client, "/api/imports/bank", "b.csv", bank_content).json()
    assert r1["source_id"] == r2["source_id"]

    ledger = _post_csv(client, "/api/imports/ledger", "l.csv", ledger_content).json()
    rzp = _post_csv(
        client, "/api/imports/razorpay-settlements", "r.json", settlements_content, "application/json"
    ).json()

    source_ids = {r1["source_id"], ledger["source_id"], rzp["source_id"]}
    assert len(source_ids) == 3

    kinds = {r1["source_kind"], ledger["source_kind"], rzp["source_kind"]}
    assert kinds == {spec[0] for spec in SOURCE_KINDS.values()}


@pytest.mark.usefixtures("clean_tables")
def test_malformed_bank_rows_reported_not_fatal(client, session_factory):
    content = (
        "txn_ref,value_date,description,credit_amount_inr,currency\n"
        "BNKOK1,2026-07-01,fine,10.00,INR\n"
        "BNKBAD,2026-07-02,bad money,abc,INR\n"
        "BNKDATE,not-a-date,bad date,30.00,INR\n"
        ",2026-07-03,missing ref,40.00,INR\n"
        "BNKNEG,2026-07-04,negative,-5.00,INR\n"
        "BNKCUR,2026-07-05,lowercase currency,60.00,inr\n"
        "BNKEXTRA,2026-07-08,three decimals,70.123,INR\n"
    ).encode("utf-8")
    response = _post_csv(client, "/api/imports/bank", "mixed.csv", content)
    assert response.status_code == 200
    body = response.json()
    assert body["inserted"] == 2
    assert body["failed_rows"] == 5
    failed_rows = {e["row_number"] for e in body["errors"]}
    assert failed_rows == {3, 4, 5, 6, 8}
    assert all(e["error"] for e in body["errors"])

    with session_factory() as db:
        currencies = {
            t.external_id: t.currency
            for t in db.execute(select(Transaction)).scalars().all()
        }
        assert currencies["BNKCUR"] == "INR"


@pytest.mark.usefixtures("clean_tables")
def test_missing_required_column_is_fatal(client):
    content = b"ref,value_date,credit_amount_inr,currency\nA,2026-07-01,10.00,INR\n"
    response = _post_csv(client, "/api/imports/bank", "bad_header.csv", content)
    assert response.status_code == 400
    assert "missing required columns" in response.json()["detail"]


@pytest.mark.usefixtures("clean_tables")
def test_malformed_razorpay_items_reported_not_fatal(client):
    payload = {
        "entity": "collection",
        "count": 3,
        "items": [
            {"id": "setl_ok1", "entity": "settlement", "amount": 152400, "status": "processed",
             "fees": 300, "tax": 54, "utr": "AXIB1111111111", "created_at": 1751381400},
            {"id": "setl_float", "entity": "settlement", "amount": 1524.5, "status": "processed",
             "fees": 300, "tax": 54, "utr": "AXIB2222222222", "created_at": 1751381400},
            {"id": "setl_ok2", "entity": "settlement", "amount": 99000, "status": "processed",
             "fees": 0, "tax": 0, "utr": "AXIB3333333333", "created_at": 1751467800},
        ],
    }
    content = json.dumps(payload).encode("utf-8")
    response = _post_csv(
        client, "/api/imports/razorpay-settlements", "r.json", content, "application/json"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["inserted"] == 2
    assert body["failed_rows"] == 1
    assert any("amount" in e["error"] or "1524.5" in e["error"] for e in body["errors"])


@pytest.mark.usefixtures("clean_tables")
def test_invalid_json_is_fatal_400(client):
    response = _post_csv(
        client, "/api/imports/razorpay-settlements", "broken.json",
        b"{not json at all", "application/json",
    )
    assert response.status_code == 400


@pytest.mark.usefixtures("clean_tables")
def test_raw_payload_contains_no_truth_labels(client, bank_content, ledger_content, settlements_content, engine):
    assert _post_csv(client, "/api/imports/bank", "b.csv", bank_content).json()["inserted"] == 100
    assert _post_csv(client, "/api/imports/ledger", "l.csv", ledger_content).json()["inserted"] == 90
    assert _post_csv(
        client, "/api/imports/razorpay-settlements", "r.json", settlements_content, "application/json"
    ).json()["inserted"] == 95

    with engine.connect() as conn:
        payloads = conn.execute(select(Transaction.raw_payload)).scalars().all()
    assert len(payloads) == 285
    for payload in payloads:
        leaks = find_label_leaks(payload)
        assert leaks == [], f"label leak in stored raw_payload: {leaks}"


@pytest.mark.usefixtures("clean_tables")
def test_all_stored_money_is_integer_paise(client, bank_content, ledger_content, settlements_content, engine):
    _post_csv(client, "/api/imports/bank", "b.csv", bank_content)
    _post_csv(client, "/api/imports/ledger", "l.csv", ledger_content)
    _post_csv(client, "/api/imports/razorpay-settlements", "r.json", settlements_content, "application/json")

    with engine.connect() as conn:
        rows = conn.execute(
            select(
                Transaction.amount_paise,
                Transaction.gross_amount_paise,
                Transaction.fee_paise,
                Transaction.tax_paise,
                Transaction.refund_amount_paise,
            )
        ).all()
    assert len(rows) == 285
    for row in rows:
        for value in row:
            if value is not None:
                assert isinstance(value, int), f"non-int money value: {value!r}"


@pytest.mark.usefixtures("clean_tables")
def test_ingestion_runs_tracked_with_counts(client, bank_content, engine):
    response = _post_csv(client, "/api/imports/bank", "bank_statement.csv", bank_content)
    run_id = response.json()["ingestion_run_id"]

    from app.models import IngestionRun

    with engine.connect() as conn:
        row = conn.execute(
            select(IngestionRun.status, IngestionRun.accepted_count, IngestionRun.rejected_count, IngestionRun.file_hash)
            .where(IngestionRun.id == run_id)
        ).one()
    assert row.status == "completed"
    assert row.accepted_count == 100
    assert row.rejected_count == 0
    assert len(row.file_hash) == 64

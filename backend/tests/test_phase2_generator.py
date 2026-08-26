import csv
import hashlib
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.contracts.razorpay import RazorpaySettlementListPage
from app.services.evaluation.synthetic_generator import (
    BANK_FILE,
    CASE_COUNTS,
    GROUND_TRUTH_FILE,
    LEDGER_FILE,
    SETTLEMENTS_FILE,
    GenerationResult,
    SyntheticDataGenerator,
    find_label_leaks,
    parse_rupees_to_paise,
    rupees_from_paise,
    write_fixture_files,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_synthetic_data.py"


@pytest.fixture(scope="module")
def generated(tmp_path_factory) -> GenerationResult:
    return SyntheticDataGenerator(seed=42).generate()


@pytest.fixture(scope="module")
def generated_dir(tmp_path_factory, generated) -> Path:
    out = tmp_path_factory.mktemp("fixtures") / "synthetic"
    write_fixture_files(generated, out)
    return out


def test_generator_emits_exactly_100_cases(generated):
    cases = generated.cases
    assert len(cases) == 100
    type_counts = {}
    for case in cases.values():
        type_counts[case["case_type"]] = type_counts.get(case["case_type"], 0) + 1
    assert type_counts == CASE_COUNTS == {
        "perfect_match": 60,
        "fee_deduction": 15,
        "partial_refund": 10,
        "duplicate_utr": 5,
        "unrecognized_credit": 10,
    }


def test_generated_source_records_are_flat(generated):
    for settlement in generated.settlements:
        assert isinstance(settlement, dict)
        for key, value in settlement.items():
            assert not isinstance(value, (dict, list, tuple)), f"nested value at {key}"
            assert value is not None, f"None value at {key}"

    for rows in (generated.bank_rows, generated.ledger_rows):
        for row in rows:
            assert isinstance(row, dict)
            for key, value in row.items():
                assert isinstance(value, str), f"{key} must serialize as a plain string"
                assert value is not None


def test_source_files_contain_no_truth_labels(generated_dir):
    settlements = json.loads((generated_dir / SETTLEMENTS_FILE).read_text(encoding="utf-8"))
    bank_payload = {"bank_rows": list(csv.DictReader(io.StringIO((generated_dir / BANK_FILE).read_text(encoding="utf-8"))))}
    ledger_payload = {"ledger_rows": list(csv.DictReader(io.StringIO((generated_dir / LEDGER_FILE).read_text(encoding="utf-8"))))}

    for payload in (settlements, bank_payload, ledger_payload):
        leaks = find_label_leaks(payload)
        assert leaks == [], f"label leak detected: {leaks}"


def test_unrecognized_and_duplicate_case_shape(generated):
    duplicate_settlement_ids = set()
    unrecognized_bank_refs = set()
    for case in generated.cases.values():
        ids = case["source_ids"]
        if case["case_type"] == "duplicate_utr":
            assert len(ids["razorpay"]) == 2
            duplicate_settlement_ids.update(ids["razorpay"])
        if case["case_type"] == "unrecognized_credit":
            assert ids["razorpay"] == []
            assert len(ids["ledger"]) == 0
            unrecognized_bank_refs.update(ids["bank"])

    assert len(duplicate_settlement_ids) == 10

    all_bank_refs = {row["txn_ref"] for row in generated.bank_rows}
    all_settlement_ids = {s["id"] for s in generated.settlements}
    assert unrecognized_bank_refs <= all_bank_refs
    assert unrecognized_bank_refs.isdisjoint(
        {ref for c in generated.cases.values() if c["case_type"] != "unrecognized_credit" for ref in c["source_ids"]["bank"]}
    )
    assert all_settlement_ids.isdisjoint(unrecognized_bank_refs)


def test_money_conversion_never_uses_float():
    assert parse_rupees_to_paise("19.99") == 1999
    assert parse_rupees_to_paise("0.10") == 10
    assert parse_rupees_to_paise("1524.00") == 152400
    assert parse_rupees_to_paise(19) == 1900
    with pytest.raises(TypeError):
        parse_rupees_to_paise(19.99)

    for paise in (1, 5, 99, 1999, 152400, 50_000_01):
        text = rupees_from_paise(paise)
        assert isinstance(text, str)
        assert parse_rupees_to_paise(text) == paise

    with pytest.raises(TypeError):
        rupees_from_paise(1999.0)


def test_duplicate_utr_cases_present(generated):
    utr_counts: dict[str, int] = {}
    for settlement in generated.settlements:
        utr = settlement["utr"]
        utr_counts[utr] = utr_counts.get(utr, 0) + 1

    duplicated = {utr: n for utr, n in utr_counts.items() if n > 1}
    assert len(duplicated) == 5
    assert all(n == 2 for n in duplicated.values())
    total_dup_rows = sum(n for _, n in duplicated.items())
    assert total_dup_rows == 10


def test_all_money_values_are_integer_paise(generated):
    for settlement in generated.settlements:
        for key in ("amount", "fees", "tax"):
            value = settlement[key]
            assert isinstance(value, int) and not isinstance(value, bool), (
                f"{key} must be int paise"
            )

    for row in generated.bank_rows + generated.ledger_rows:
        for key, value in row.items():
            if key.endswith("_inr"):
                assert parse_rupees_to_paise(value) >= 0


def test_generator_is_deterministic_for_same_seed(tmp_path):
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    result_a = SyntheticDataGenerator(seed=7).generate()
    result_b = SyntheticDataGenerator(seed=7).generate()
    write_fixture_files(result_a, out_a)
    write_fixture_files(result_b, out_b)

    names = [SETTLEMENTS_FILE, BANK_FILE, LEDGER_FILE, GROUND_TRUTH_FILE]
    for name in names:
        hash_a = hashlib.sha256((out_a / name).read_bytes()).hexdigest()
        hash_b = hashlib.sha256((out_b / name).read_bytes()).hexdigest()
        assert hash_a == hash_b, f"{name} differs between runs"

    result_c = SyntheticDataGenerator(seed=8).generate()
    assert result_c.settlements != result_a.settlements


def test_manifest_hashes_match_written_files(generated_dir):
    manifest = json.loads((generated_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["synthetic"] is True
    for name, expected_hash in manifest["sha256"].items():
        actual_hash = hashlib.sha256((generated_dir / name).read_bytes()).hexdigest()
        assert actual_hash == expected_hash, f"{name} does not match manifest"


def test_cli_generates_fixtures(tmp_path):
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--seed", "42", "--out", str(tmp_path)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    for name in (SETTLEMENTS_FILE, BANK_FILE, LEDGER_FILE, GROUND_TRUTH_FILE, "manifest.json"):
        assert (tmp_path / name).exists()


def test_settlements_ingest_through_phase1_contract(generated_dir):
    payload = json.loads((generated_dir / SETTLEMENTS_FILE).read_text(encoding="utf-8"))
    page = RazorpaySettlementListPage.model_validate(payload)
    assert page.entity == "collection"
    assert page.count == len(page.items) == 95
    for item in page.items:
        assert isinstance(item.amount, int)
        assert item.status == "processed"


def test_csv_rows_ingest_through_phase1_normalization(generated, generated_dir):
    bank_rows = list(csv.DictReader(io.StringIO((generated_dir / BANK_FILE).read_text(encoding="utf-8"))))
    ledger_rows = list(csv.DictReader(io.StringIO((generated_dir / LEDGER_FILE).read_text(encoding="utf-8"))))

    assert len(bank_rows) == 100
    assert len(ledger_rows) == 90

    bank_by_ref = {}
    for row in bank_rows:
        paise = parse_rupees_to_paise(row["credit_amount_inr"])
        assert isinstance(paise, int)
        bank_by_ref[row["txn_ref"]] = (paise, row["value_date"])

    ref_to_case = {
        ref: case
        for case in generated.cases.values()
        for ref in case["source_ids"]["bank"]
    }
    assert set(bank_by_ref) == set(ref_to_case)


@pytest.mark.usefixtures("clean_tables")
def test_generated_settlement_row_inserts_into_phase1_schema(db, generated_dir):
    import uuid
    from datetime import date

    from app.models import IngestionRun, Source, Transaction

    payload = json.loads((generated_dir / SETTLEMENTS_FILE).read_text(encoding="utf-8"))
    item = payload["items"][0]

    source = Source(org_id=uuid.uuid4(), kind="razorpay_settlements", name="synthetic")
    db.add(source)
    db.flush()
    run = IngestionRun(source_id=source.id, file_name="razorpay_settlements.json", status="completed")
    db.add(run)
    db.flush()

    transaction = Transaction(
        org_id=source.org_id,
        source_id=source.id,
        ingestion_run_id=run.id,
        external_id=item["id"],
        transaction_kind="settlement",
        direction="credit",
        amount_paise=item["amount"],
        gross_amount_paise=item["amount"],
        fee_paise=item["fees"],
        tax_paise=item["tax"],
        currency=item.get("currency", "INR"),
        effective_date=date.fromtimestamp(item["created_at"]),
        utr=item["utr"],
        raw_payload=item,
        normalization_version="v1",
    )
    db.add(transaction)
    db.commit()

    assert transaction.amount_paise == item["amount"]
    assert isinstance(transaction.amount_paise, int)

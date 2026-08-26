import uuid
from pathlib import Path

import pytest

from app.services.ingestion.importers import (
    ingest_bank_csv,
    ingest_ledger_csv,
    ingest_razorpay_settlements,
)
from app.services.matching.deterministic import start_reconciliation_run

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "fixtures" / "synthetic"


@pytest.fixture()
def wired(client, clean_tables, session_factory):
    with session_factory() as db:
        ingest_bank_csv(db, (FIXTURES_DIR / "bank_statement.csv").read_bytes())
        ingest_ledger_csv(db, (FIXTURES_DIR / "ledger.csv").read_bytes())
        ingest_razorpay_settlements(
            db, (FIXTURES_DIR / "razorpay_settlements.json").read_bytes()
        )
        run = start_reconciliation_run(db)
        db.commit()
        return {"run_id": run["run_id"], "client": client}


def test_list_runs_returns_latest_first(wired):
    runs = wired["client"].get("/api/reconciliation-runs").json()
    assert len(runs) == 1
    assert runs[0]["run_id"] == wired["run_id"]
    assert runs[0]["summary"]["matched_bank_transactions"] == 75


def test_run_matches_endpoint(wired):
    matches = (
        wired["client"]
        .get(f"/api/reconciliation-runs/{wired['run_id']}/matches")
        .json()
    )
    assert len(matches) == 75
    for group in matches:
        assert group["strategy"] in ("EXACT_UTR_AMOUNT", "LEDGER_NET_EXACT", "AMOUNT_DATE_WINDOW")
        assert len(group["members"]) >= 2
        roles = {m["role"] for m in group["members"]}
        assert "bank_credit" in roles
        for member in group["members"]:
            assert isinstance(member["amount_paise"], int)


def test_run_matches_unknown_run_404(client):
    response = client.get(f"/api/reconciliation-runs/{uuid.uuid4()}/matches")
    assert response.status_code == 404


def test_audit_logs_endpoint_filters_by_entity(wired):
    client = wired["client"]
    excs = client.get("/api/exceptions").json()
    target = excs[0]

    decided = client.post(
        f"/api/exceptions/{target['id']}/decision",
        json={"action": "reject", "reason": "not supported by evidence"},
    )
    assert decided.status_code == 200

    logs = client.get(
        "/api/exceptions/audit-logs",
        params={"entity_type": "exception", "entity_id": target["id"]},
    ).json()
    assert len(logs) == 1
    assert logs[0]["action"] == "exception_reject"
    assert logs[0]["reason"] == "not supported by evidence"

    all_logs = client.get("/api/exceptions/audit-logs").json()
    assert len(all_logs) == 1

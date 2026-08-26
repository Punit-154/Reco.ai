import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import BigInteger, insert, select, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import sessionmaker

from app.models import (
    Actor,
    AuditLog,
    Base,
    ExceptionRecord,
    IngestionRun,
    MatchGroup,
    MatchMember,
    Source,
    Transaction,
    WebhookEvent,
)

MONEY_COLUMNS = {
    "transactions": [
        "amount_paise",
        "gross_amount_paise",
        "fee_paise",
        "tax_paise",
        "refund_amount_paise",
    ],
    "match_groups": ["expected_amount_paise", "actual_amount_paise", "delta_paise"],
    "match_members": ["allocated_paise"],
    "evaluation_runs": ["seed"],
}

DEMO_ACTOR_ID = uuid.UUID("7fa528e3-07b7-5613-b90d-e89b562882a3")


def test_money_columns_are_bigint():
    metadata = Base.metadata
    for table_name, columns in MONEY_COLUMNS.items():
        table = metadata.tables[table_name]
        for column_name in columns:
            column = table.columns[column_name]
            assert isinstance(column.type, BigInteger), (
                f"{table_name}.{column_name} must be BIGINT"
            )


@pytest.mark.usefixtures("clean_tables")
def test_seed_demo_actor(db):
    actor = db.execute(select(Actor).where(Actor.name == "demo_finance_controller")).scalar_one()
    assert actor.id == DEMO_ACTOR_ID
    assert actor.is_demo is True


@pytest.mark.usefixtures("clean_tables")
def test_insert_core_records(db):
    source = Source(org_id=uuid.uuid4(), kind="razorpay_settlements", name="fixture-src")
    db.add(source)
    db.flush()

    run = IngestionRun(
        source_id=source.id,
        file_name="settlements.json",
        file_hash="deadbeef",
        status="completed",
        accepted_count=1,
        rejected_count=0,
    )
    db.add(run)
    db.flush()

    transaction = Transaction(
        org_id=source.org_id,
        source_id=source.id,
        ingestion_run_id=run.id,
        external_id="setl_demo_001",
        transaction_kind="settlement",
        direction="credit",
        amount_paise=152400,
        gross_amount_paise=152400,
        fee_paise=300,
        tax_paise=54,
        currency="INR",
        effective_date=date(2026, 8, 20),
        utr="DEMOAXIS001",
        raw_payload={"id": "setl_demo_001"},
        normalization_version="v1",
    )
    db.add(transaction)
    db.flush()

    group = MatchGroup(
        org_id=source.org_id,
        strategy="UTR_EXACT",
        status="matched",
        deterministic_score=1.000,
        expected_amount_paise=152400,
        actual_amount_paise=152400,
        delta_paise=0,
        rule_trace={"candidates": 1},
    )
    db.add(group)
    db.flush()

    db.add(
        MatchMember(
            match_group_id=group.id,
            transaction_id=transaction.id,
            role="razorpay_settlement",
            allocated_paise=152400,
        )
    )

    db.add(
        ExceptionRecord(
            transaction_id=transaction.id,
            status="unresolved",
            taxonomy="insufficient_evidence",
            confidence=0.500,
            model_name="fake",
            prompt_version="v0",
        )
    )
    db.flush()

    db.add(
        AuditLog(
            actor_id=DEMO_ACTOR_ID,
            action="create_source",
            entity_type="source",
            entity_id=str(source.id),
            new_state={"name": "fixture-src"},
            reason="phase1 smoke",
        )
    )
    db.commit()

    assert db.execute(select(Transaction)).scalars().all()
    assert db.execute(select(MatchGroup)).scalars().all()
    assert db.execute(select(ExceptionRecord)).scalars().all()
    assert db.execute(select(AuditLog)).scalars().all()


@pytest.mark.usefixtures("clean_tables")
def test_transaction_unique_source_external_id(db):
    source = Source(org_id=uuid.uuid4(), kind="bank_statement", name="bank")
    db.add(source)
    db.flush()

    def make_txn():
        return Transaction(
            org_id=source.org_id,
            source_id=source.id,
            external_id="row-1",
            transaction_kind="bank_credit",
            direction="credit",
            amount_paise=1999,
            currency="INR",
            effective_date=date(2026, 8, 21),
            normalization_version="v1",
        )

    db.add(make_txn())
    db.commit()

    db.add(make_txn())
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.usefixtures("clean_tables")
def test_webhook_provider_event_id_unique(db):
    def make_event():
        return WebhookEvent(
            provider_event_id="evt_demo_001",
            event_type="settlement.processed",
            signature_valid=True,
            raw_payload={"event": "settlement.processed"},
        )

    db.add(make_event())
    db.commit()

    db.add(make_event())
    with pytest.raises(IntegrityError):
        db.commit()


@pytest.mark.usefixtures("clean_tables")
def test_audit_logs_are_append_only(db):
    log = AuditLog(
        actor_id=DEMO_ACTOR_ID,
        action="seed_check",
        entity_type="audit_log",
        new_state={"v": 1},
    )
    db.add(log)
    db.commit()

    with pytest.raises(DBAPIError):
        db.execute(update(AuditLog).where(AuditLog.id == log.id).values(action="tampered"))
        db.commit()


@pytest.mark.usefixtures("clean_tables")
def test_audit_logs_reject_delete(db):
    log = AuditLog(
        actor_id=DEMO_ACTOR_ID,
        action="seed_check2",
        entity_type="audit_log",
        new_state={"v": 1},
    )
    db.add(log)
    db.commit()

    with pytest.raises(DBAPIError):
        db.delete(log)
        db.commit()


def test_health_endpoint(test_database_url):
    from fastapi.testclient import TestClient

    from app.db import get_db, make_engine
    from app.main import app

    engine = make_engine(test_database_url)
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"

import asyncio
import hashlib
import hmac
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.config import Settings, get_settings
from app.models import Transaction, WebhookEvent
from app.services.evaluation.synthetic_generator import find_label_leaks

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACT_WEBHOOK = json.loads(
    (REPO_ROOT / "docs" / "contracts" / "razorpay_settlement_processed_webhook.json").read_text(
        encoding="utf-8"
    )
)

WEBHOOK_SECRET = "test_webhook_secret"


def _signed_headers(body: bytes, event_id: str, secret: str = WEBHOOK_SECRET) -> dict:
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return {
        "x-razorpay-signature": signature,
        "x-razorpay-event-id": event_id,
    }


def _settlement_payload(
    settlement_id: str,
    utr: str,
    amount: int = 152400,
    created_at: int = 1763019089,
) -> dict:
    payload = json.loads(json.dumps(CONTRACT_WEBHOOK))
    entity = payload["payload"]["settlement"]["entity"]
    entity["id"] = settlement_id
    entity["utr"] = utr
    entity["amount"] = amount
    entity["created_at"] = created_at
    return payload


@pytest.fixture()
def webhook_client(client):
    def _override_settings():
        return Settings(razorpay_webhook_secret=WEBHOOK_SECRET, _env_file=None)

    client.app.dependency_overrides[get_settings] = _override_settings
    return client


@pytest.fixture()
def post_event(webhook_client):
    def _post(payload: dict, event_id: str, secret: str = WEBHOOK_SECRET):
        body = json.dumps(payload).encode("utf-8")
        return webhook_client.post(
            "/api/webhooks/razorpay",
            content=body,
            headers=_signed_headers(body, event_id, secret),
        )

    return _post


@pytest.mark.usefixtures("clean_tables")
def test_invalid_signature_rejected(webhook_client, engine):
    body = json.dumps(CONTRACT_WEBHOOK).encode("utf-8")
    headers = _signed_headers(body, "evt_bad_sig", secret="wrong_secret")
    response = webhook_client.post("/api/webhooks/razorpay", content=body, headers=headers)

    assert response.status_code == 400
    assert "signature" in response.json()["detail"].lower()

    with engine.connect() as conn:
        count = len(conn.execute(select(WebhookEvent.id)).scalars().all())
    assert count == 0


@pytest.mark.usefixtures("clean_tables")
def test_missing_signature_header_rejected(webhook_client):
    body = json.dumps(CONTRACT_WEBHOOK).encode("utf-8")
    response = webhook_client.post(
        "/api/webhooks/razorpay",
        content=body,
        headers={"x-razorpay-event-id": "evt_nosig"},
    )
    assert response.status_code == 400


@pytest.mark.usefixtures("clean_tables")
def test_tampered_body_rejected(webhook_client):
    signed_body = json.dumps(
        _settlement_payload("setl_tamper_1", "AXIB1000000001")
    ).encode("utf-8")
    tampered_body = json.dumps(
        _settlement_payload("setl_tamper_1", "AXIB9999999999")
    ).encode("utf-8")

    response = webhook_client.post(
        "/api/webhooks/razorpay",
        content=tampered_body,
        headers=_signed_headers(signed_body, "evt_tamper"),
    )
    assert response.status_code == 400


@pytest.mark.usefixtures("clean_tables")
def test_valid_signature_accepted_and_transaction_created(post_event, session_factory):
    payload = _settlement_payload("setl_ok_001", "AXIB2000000001", amount=250000)
    response = post_event(payload, "evt_valid_001")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "processed"
    assert body["transaction_created"] is True

    with session_factory() as db:
        event = db.execute(
            select(WebhookEvent).where(WebhookEvent.provider_event_id == "evt_valid_001")
        ).scalar_one()
        assert event.event_type == "settlement.processed"
        assert event.signature_valid is True
        assert event.processed_at is not None

        txn = db.execute(
            select(Transaction).where(Transaction.external_id == "setl_ok_001")
        ).scalar_one()
        assert txn.amount_paise == 250000
        assert isinstance(txn.amount_paise, int)
        assert txn.fee_paise == CONTRACT_WEBHOOK["payload"]["settlement"]["entity"]["fees"]
        assert txn.tax_paise == CONTRACT_WEBHOOK["payload"]["settlement"]["entity"]["tax"]
        assert txn.utr == "AXIB2000000001"
        assert txn.transaction_kind == "settlement"
        assert find_label_leaks(txn.raw_payload) == []


@pytest.mark.usefixtures("clean_tables")
def test_duplicate_event_id_is_skipped(post_event, session_factory):
    payload = _settlement_payload("setl_dup_evt", "AXIB3000000001")

    first = post_event(payload, "evt_dup_001")
    second = post_event(payload, "evt_dup_001")

    assert first.status_code == 200 and first.json()["status"] == "processed"
    assert second.status_code == 200
    assert second.json() == {
        "status": "skipped",
        "reason": "duplicate_event",
        "event_id": "evt_dup_001",
    }

    with session_factory() as db:
        events = db.execute(select(WebhookEvent)).scalars().all()
        txns = db.execute(select(Transaction)).scalars().all()
    assert len(events) == 1
    assert len(txns) == 1


@pytest.mark.usefixtures("clean_tables")
def test_repeated_payload_does_not_duplicate_transaction(post_event, session_factory):
    payload = _settlement_payload("setl_repeat", "AXIB4000000001")

    r1 = post_event(payload, "evt_repeat_001")
    r2 = post_event(payload, "evt_repeat_002")

    assert r1.json()["status"] == "processed"
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "processed"
    assert r2.json()["transaction_created"] is False
    assert r2.json()["duplicate_transaction"] is True

    with session_factory() as db:
        txns = db.execute(
            select(Transaction).where(Transaction.external_id == "setl_repeat")
        ).scalars().all()
        events = db.execute(select(WebhookEvent)).scalars().all()
    assert len(txns) == 1
    assert len(events) == 2


@pytest.mark.parametrize("order", [["a", "b"], ["b", "a"]])
@pytest.mark.usefixtures("clean_tables")
def test_event_order_does_not_matter(post_event, session_factory, order):
    payloads = {
        "a": ("evt_order_a", _settlement_payload("setl_ord_a", "AXIB5000000001")),
        "b": ("evt_order_b", _settlement_payload("setl_ord_b", "AXIB5000000002")),
    }

    responses = [post_event(payloads[name][1], payloads[name][0]) for name in order]
    assert all(r.status_code == 200 for r in responses)

    with session_factory() as db:
        settlements = db.execute(
            select(Transaction).where(Transaction.transaction_kind == "settlement")
        ).scalars().all()

    assert {t.external_id for t in settlements} == {"setl_ord_a", "setl_ord_b"}
    assert len(settlements) == 2


@pytest.mark.usefixtures("clean_tables")
def test_same_settlement_two_events_yields_single_transaction(post_event, session_factory):
    payload_a = _settlement_payload("setl_same", "AXIB6000000001")
    payload_b = _settlement_payload("setl_same", "AXIB6000000001")

    r1 = post_event(payload_a, "evt_same_001")
    r2 = post_event(payload_b, "evt_same_002")
    assert r1.json()["status"] == "processed"
    assert r2.json()["status"] == "processed"

    with session_factory() as db:
        txns = db.execute(
            select(Transaction).where(Transaction.external_id == "setl_same")
        ).scalars().all()
    assert len(txns) == 1


@pytest.mark.usefixtures("clean_tables")
def test_settlement_created_is_stored_but_never_processed_as_webhook(post_event, session_factory):
    payload = json.loads(json.dumps(CONTRACT_WEBHOOK))
    payload["event"] = "settlement.created"
    payload["payload"]["settlement"]["entity"]["id"] = "setl_created_evt"

    response = post_event(payload, "evt_created_001")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ignored"
    assert body["reason"] == "unsupported_event_type"

    with session_factory() as db:
        events = db.execute(select(WebhookEvent)).scalars().all()
        txns = db.execute(
            select(Transaction).where(Transaction.external_id == "setl_created_evt")
        ).scalars().all()
    assert len(events) == 1
    assert len(txns) == 0


@pytest.mark.usefixtures("clean_tables")
def test_processing_failure_keeps_event_retryable(post_event, session_factory):
    payload = _settlement_payload("setl_fail", "AXIB7000000001")
    del payload["payload"]["settlement"]["entity"]["amount"]

    response = post_event(payload, "evt_fail_001")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "accepted"
    assert body["processing"] == "failed"

    with session_factory() as db:
        event = db.execute(
            select(WebhookEvent).where(WebhookEvent.provider_event_id == "evt_fail_001")
        ).scalar_one()
    assert event.signature_valid is True
    assert event.processed_at is None


def test_polling_stub_requires_no_network():
    from app.services.razorpay.polling import (
        FixtureSettlementsPoller,
        HttpSettlementsPoller,
    )

    poller = FixtureSettlementsPoller([{"id": "setl_fixture"}])
    assert poller.fetch_settlements() == [{"id": "setl_fixture"}]

    with pytest.raises(RuntimeError):
        HttpSettlementsPoller(key_id="", key_secret="")


def test_webhook_modules_have_no_live_network_calls():
    service_dirs = [
        REPO_ROOT / "backend" / "app" / "services" / "webhooks",
        REPO_ROOT / "backend" / "app" / "services" / "razorpay",
    ]
    for directory in service_dirs:
        for file in directory.glob("*.py"):
            text = file.read_text(encoding="utf-8").lower()
            assert "import requests" not in text
            assert "httpx" not in text
            assert "urllib" not in text


def test_signature_function_contract():
    import inspect

    from app.services.webhooks.razorpay import (
        compute_webhook_signature,
        validate_razorpay_webhook,
    )

    params = list(inspect.signature(compute_webhook_signature).parameters)
    assert params == ["raw_body", "secret"]

    body = b'{"entity":"event"}'
    expected = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert compute_webhook_signature(body, "s3cret") == expected

    assert asyncio.iscoroutinefunction(validate_razorpay_webhook)

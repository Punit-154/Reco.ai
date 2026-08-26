import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.contracts.razorpay import (
    RazorpaySettlementListPage,
    RazorpayWebhookEvent,
)

CONTRACTS_DIR = Path(__file__).resolve().parents[2] / "docs" / "contracts"

SECRET_PATTERNS = [
    "rzp_live_",
    "rzp_test_",
    "gsk_",
    "sk-",
    "AKIA",
    "ghp_",
    "xoxb-",
    "BEGIN PRIVATE KEY",
]

FORBIDDEN_LABEL_KEYS = {
    "scenario",
    "expected_class",
    "expected_outcome",
    "duplicate_flag",
    "unrecognized",
    "ground_truth",
    "label",
}


def _iter_strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _iter_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_strings(item)
    elif isinstance(value, str):
        yield value


def _load(name: str) -> dict:
    with open(CONTRACTS_DIR / name, encoding="utf-8") as f:
        return json.load(f)


def test_settlement_fixture_parses_as_contract():
    page = RazorpaySettlementListPage.model_validate(_load("razorpay_settlements_example.json"))
    assert page.entity == "collection"
    assert page.count == len(page.items)
    settlement = page.items[0]
    assert isinstance(settlement.amount, int) and not isinstance(settlement.amount, bool)
    assert settlement.amount == 152400
    assert settlement.fees == 300
    assert settlement.tax == 54
    assert settlement.utr == "DEMOAXIS001"


def test_webhook_fixture_is_settlement_processed():
    event = RazorpayWebhookEvent.model_validate(
        _load("razorpay_settlement_processed_webhook.json")
    )
    assert event.event == "settlement.processed"
    assert "settlement" in event.contains
    entity = event.payload["settlement"]["entity"]
    assert entity["id"] == "setl_demo_001"
    assert entity["amount"] == 152400


def test_contract_rejects_float_money():
    payload = _load("razorpay_settlements_example.json")
    payload["items"][0]["amount"] = 1524.0
    with pytest.raises(ValidationError):
        RazorpaySettlementListPage.model_validate(payload)


def test_contracts_have_no_credentials_or_customer_data():
    for path in CONTRACTS_DIR.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        for text_value in _iter_strings(data):
            for pattern in SECRET_PATTERNS:
                assert pattern not in text_value, f"{path.name} contains {pattern}"
        assert not any(
            key in FORBIDDEN_LABEL_KEYS for key in _iter_strings(data)
        ), f"{path.name} contains a truth-label key"


@pytest.mark.parametrize("name", [
    "razorpay_settlements_example.json",
    "razorpay_settlement_processed_webhook.json",
])
def test_fixture_amounts_are_integer_paise(name: str):
    data = _load(name)

    def _walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"amount", "fees", "tax"} and item is not None:
                    assert isinstance(item, int), f"{name}:{key} is not an int"
                _walk(item)
        elif isinstance(value, list):
            for item in value:
                _walk(item)

    _walk(data)

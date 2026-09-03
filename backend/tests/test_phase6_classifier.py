import json
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import ExceptionRecord, MatchGroup
from app.services.ai.classifier import (
    ALLOWED_CATEGORIES,
    LLM_CATEGORIES,
    ClassificationCategory,
    ExceptionClassification,
    FakeExceptionClassifier,
    GroqExceptionClassifier,
    ProviderError,
    get_classifier,
)
from app.services.ai.evidence import build_evidence_pack
from app.services.ai.triage import BATCH_SIZE, classify_pending_exceptions
from app.services.ingestion.importers import (
    ingest_bank_csv,
    ingest_ledger_csv,
    ingest_razorpay_settlements,
)
from app.services.matching.deterministic import start_reconciliation_run

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "fixtures" / "synthetic"
AI_SERVICE_DIR = REPO_ROOT / "backend" / "app" / "services" / "ai"

FORBIDDEN_IN_PROMPT = (
    "ground_truth",
    "ground truth",
    "perfect_match",
    "fee_deduction",
    "partial_refund",
    "duplicate_utr",
    "unrecognized_credit",
    "expected_outcome",
    "expected_class",
)


def _sample_pack(reason_code: str = "NO_CANDIDATE") -> dict:
    return {
        "exception_id": "11111111-1111-1111-1111-111111111111",
        "reason_code": reason_code,
        "deterministic_explanation": "no candidate matched deterministically",
        "bank_transaction": {
            "transaction_id": "22222222-2222-2222-2222-222222222222",
            "external_id": "BNKTEST1",
            "kind": "bank_credit",
            "amount_paise": 100000,
            "currency": "INR",
            "effective_date": "2026-07-01",
            "normalized_utr": None,
        },
        "related_settlements": [
            {
                "transaction_id": "33333333-3333-3333-3333-333333333333",
                "external_id": "setl_test1",
                "amount_paise": 150000,
                "fee_paise": 0,
                "tax_paise": 0,
                "currency": "INR",
                "effective_date": "2026-07-01",
                "normalized_utr": None,
            }
        ],
        "candidate_deltas": [{"settlement_external_id": "setl_test1", "delta_paise": 50000}],
    }


def test_fake_classifier_is_deterministic():
    classifier = FakeExceptionClassifier()
    pack = _sample_pack("MULTIPLE_SETTLEMENT_CANDIDATES")
    first = classifier.classify(pack)
    second = classifier.classify(pack)
    assert first == second

    result = classifier.classify(_sample_pack("NO_CANDIDATE"))
    assert result.category == ClassificationCategory.UNRECOGNIZED_CREDIT
    assert result.requires_human_review is True


def test_fake_classifier_maps_all_residue_reasons():
    classifier = FakeExceptionClassifier()

    dup = classifier.classify(_sample_pack("MULTIPLE_SETTLEMENT_CANDIDATES"))
    assert dup.category == ClassificationCategory.DUPLICATE_UTR
    assert len(dup.evidence_transaction_ids) == 2

    unrec = classifier.classify(_sample_pack("NO_CANDIDATE"))
    assert unrec.category == ClassificationCategory.UNRECOGNIZED_CREDIT

    refund = classifier.classify(_sample_pack("NO_DETERMINISTIC_MATCH"))
    assert refund.category == ClassificationCategory.REFUND_LAG
    assert 0 <= refund.confidence <= 100


def test_strict_json_validation():
    with pytest.raises(Exception):
        ExceptionClassification.model_validate(
            {
                "category": "FEE_DELTA",
                "confidence": 101,
                "explanation": "too confident",
                "requires_human_review": True,
            }
        )

    with pytest.raises(Exception):
        ExceptionClassification.model_validate(
            {
                "category": "NOT_A_CATEGORY",
                "confidence": 50,
                "explanation": "bad category",
                "requires_human_review": True,
            }
        )

    ok = ExceptionClassification.model_validate(
        {
            "category": "AMBIGUOUS_MATCH",
            "confidence": 60,
            "explanation": "fine",
            "evidence_transaction_ids": ["x"],
        }
    )
    assert ok.requires_human_review is True
    assert {c.value for c in ClassificationCategory} == set(ALLOWED_CATEGORIES)


class _ScriptedGroq(GroqExceptionClassifier):
    def __init__(self, script):
        super().__init__(api_key="key", model="test-model")
        self.script = list(script)
        self.calls: list[list[dict]] = []

    def _transport(self, messages):  # noqa: D102 - test seam
        self.calls.append(messages)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def _valid_model_json() -> str:
    return json.dumps(
        {
            "category": "UNRECOGNIZED_CREDIT",
            "confidence": 82,
            "explanation": "no matching settlement found",
            "evidence_transaction_ids": ["22222222-2222-2222-2222-222222222222"],
            "requires_human_review": True,
        }
    )


def test_groq_parses_valid_json_and_forces_review_flag():
    scripted = _ScriptedGroq(
        [
            json.dumps(
                {
                    "category": "REFUND_LAG",
                    "confidence": 70,
                    "explanation": "refund pending",
                    "evidence_transaction_ids": [],
                    "requires_human_review": False,
                }
            )
        ]
    )
    result = scripted.classify(_sample_pack("NO_DETERMINISTIC_MATCH"))
    assert result.category == ClassificationCategory.REFUND_LAG
    assert result.requires_human_review is True


def test_invalid_json_becomes_invalid_model_output_after_one_repair():
    scripted = _ScriptedGroq(["not json at all", "still not json"])
    result = scripted.classify(_sample_pack("NO_CANDIDATE"))

    assert result.category == ClassificationCategory.INVALID_MODEL_OUTPUT
    assert result.confidence == 0
    assert result.requires_human_review is True
    assert len(scripted.calls) == 2


def test_repair_retry_succeeds_on_second_valid_json():
    scripted = _ScriptedGroq(["oops", _valid_model_json()])
    result = scripted.classify(_sample_pack("NO_CANDIDATE"))

    assert result.category == ClassificationCategory.UNRECOGNIZED_CREDIT
    assert result.confidence == 82
    assert len(scripted.calls) == 2


def test_transient_provider_error_retries_once_then_model_unavailable():
    attempts = {"n": 0}

    def flaky_transport(messages):
        attempts["n"] += 1
        raise ProviderError("timeout")

    class _Flaky(GroqExceptionClassifier):
        def _transport(self, messages):
            return flaky_transport(messages)

    classifier = _Flaky(api_key="k", model="m")
    result = classifier.classify(_sample_pack("NO_CANDIDATE"))

    assert result.category == ClassificationCategory.MODEL_UNAVAILABLE
    assert attempts["n"] == 2
    assert result.requires_human_review is True


def test_hard_http_rejection_does_not_retry():
    calls = {"n": 0}

    class _HardFail(GroqExceptionClassifier):
        def _transport(self, messages):
            calls["n"] += 1
            raise RuntimeError("provider rejected request: 401")

    classifier = _HardFail(api_key="k", model="m")
    result = classifier.classify(_sample_pack("NO_CANDIDATE"))

    assert result.category == ClassificationCategory.MODEL_UNAVAILABLE
    assert calls["n"] == 1


def test_prompt_contains_no_placeholders_or_ground_truth():
    classifier = GroqExceptionClassifier(api_key="k", model="m")
    pack = _sample_pack("NO_DETERMINISTIC_MATCH")
    system_prompt, user_prompt = classifier.render_prompt(pack)

    facts_json = json.dumps(pack, default=str)
    for forbidden in FORBIDDEN_IN_PROMPT:
        assert forbidden not in facts_json.lower(), (
            f"evidence pack leaks label token: {forbidden}"
        )

    non_label_tokens = [
        t for t in FORBIDDEN_IN_PROMPT if t not in {c.value.lower() for c in ClassificationCategory}
    ]
    lowered = user_prompt.lower()
    for token in non_label_tokens:
        assert token not in lowered, f"prompt leaks label token: {token}"

    for category in LLM_CATEGORIES:
        assert category in user_prompt
    assert "100000" in user_prompt

    assert "ground truth" not in system_prompt.lower()


def test_ai_service_modules_never_reference_ground_truth_files():
    for file in AI_SERVICE_DIR.glob("*.py"):
        text = file.read_text(encoding="utf-8").lower()
        assert "ground_truth" not in text, f"{file.name} references ground_truth"
        assert "fixtures/" not in text, f"{file.name} reads fixture paths"


@pytest.fixture()
def residue_loaded(client, clean_tables, engine, session_factory):
    def _ingest():
        with session_factory() as db:
            ingest_bank_csv(db, (FIXTURES_DIR / "bank_statement.csv").read_bytes())
            ingest_ledger_csv(db, (FIXTURES_DIR / "ledger.csv").read_bytes())
            ingest_razorpay_settlements(
                db, (FIXTURES_DIR / "razorpay_settlements.json").read_bytes()
            )
            db.commit()
            start_reconciliation_run(db)
            db.commit()

    _ingest()
    return {"session_factory": session_factory, "client": client}


def test_pending_residue_exceptions_get_classified(residue_loaded):
    sf = residue_loaded["session_factory"]
    client = residue_loaded["client"]

    response = client.post("/api/exceptions/classify-pending")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["classifier"] == "fake"
    assert body["pending_found"] == 25
    assert body["classified"] == 25
    assert body["by_category"] == {
        "DUPLICATE_UTR": 5,
        "UNRECOGNIZED_CREDIT": 10,
        "REFUND_LAG": 10,
    }

    with sf() as db:
        exceptions = db.execute(select(ExceptionRecord)).scalars().all()
        groups = db.execute(select(MatchGroup)).scalars().all()

    assert len(groups) == 75
    classified_rows = [e for e in exceptions if e.response is not None]
    assert len(classified_rows) == 25
    for exc in classified_rows:
        assert exc.model_name == "fake"
        assert exc.prompt_version == "v0-fake"
        assert exc.confidence is not None and 0 <= float(exc.confidence) <= 1
        assert exc.status == "unresolved"


def test_classification_is_idempotent_per_exception(residue_loaded):
    client = residue_loaded["client"]
    sf = residue_loaded["session_factory"]

    first = client.post("/api/exceptions/classify-pending").json()
    assert first["classified"] == 25

    second_response = client.post("/api/exceptions/classify-pending")
    second = second_response.json()
    assert second["pending_found"] == 0
    assert second["classified"] == 0


def test_use_ai_without_keys_falls_back_to_fake_offline(residue_loaded):
    from app.config import Settings, get_settings

    client = residue_loaded["client"]

    def _no_groq_settings():
        return Settings(groq_api_key="", groq_model="", _env_file=None)

    client.app.dependency_overrides[get_settings] = _no_groq_settings
    try:
        response = client.post(
            "/api/exceptions/classify-pending", json={"use_ai": True}
        )
    finally:
        client.app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 200
    assert response.json()["classifier"] == "fake"


def test_get_classifier_selects_groq_only_when_configured():
    settings_stub = type("S", (), {})()
    settings_stub.groq_api_key = ""
    settings_stub.groq_model = ""
    assert isinstance(get_classifier(settings_stub, use_ai=True), FakeExceptionClassifier)

    settings_stub.groq_api_key = "k"
    settings_stub.groq_model = "llama-test"
    chosen = get_classifier(settings_stub, use_ai=True)
    assert isinstance(chosen, GroqExceptionClassifier)
    assert chosen.full_name == "groq:llama-test"

    assert isinstance(get_classifier(settings_stub, use_ai=False), FakeExceptionClassifier)


def test_batch_size_is_five():
    assert BATCH_SIZE == 5


def test_failure_categories_are_deferred_and_retryable(residue_loaded):
    sf = residue_loaded["session_factory"]

    class _DownClassifier(FakeExceptionClassifier):
        name = "down"

        def classify(self, evidence_pack):
            return ExceptionClassification(
                category=ClassificationCategory.MODEL_UNAVAILABLE,
                confidence=0,
                explanation="provider down",
                evidence_transaction_ids=[],
                requires_human_review=True,
            )

    with sf() as db:
        result = classify_pending_exceptions(db, _DownClassifier(), limit=100)
        db.commit()

    assert result["classified"] == 0
    assert result["deferred_retry"] == 25

    with sf() as db:
        rows = db.execute(select(ExceptionRecord)).scalars().all()
        assert len(rows) == 25
        assert all(r.response is None for r in rows)
        assert all(r.retry_count == 1 for r in rows)

    with sf() as db:
        recovery = classify_pending_exceptions(db, FakeExceptionClassifier(), limit=100)
        db.commit()

    assert recovery["classified"] == 25
    assert recovery["deferred_retry"] == 0

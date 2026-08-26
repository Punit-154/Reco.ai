from __future__ import annotations

import json
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

PROMPT_VERSION_FAKE = "v0-fake"
PROMPT_VERSION_GROQ = "v1-groq"

ALLOWED_CATEGORIES = (
    "FEE_DELTA",
    "REFUND_LAG",
    "FX_ROUNDING",
    "DUPLICATE_UTR",
    "UNRECOGNIZED_CREDIT",
    "AMBIGUOUS_MATCH",
    "MODEL_UNAVAILABLE",
    "INVALID_MODEL_OUTPUT",
)

FAILURE_CATEGORIES = {"MODEL_UNAVAILABLE", "INVALID_MODEL_OUTPUT"}


class ClassificationCategory(str, Enum):
    FEE_DELTA = "FEE_DELTA"
    REFUND_LAG = "REFUND_LAG"
    FX_ROUNDING = "FX_ROUNDING"
    DUPLICATE_UTR = "DUPLICATE_UTR"
    UNRECOGNIZED_CREDIT = "UNRECOGNIZED_CREDIT"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    INVALID_MODEL_OUTPUT = "INVALID_MODEL_OUTPUT"


class ExceptionClassification(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: ClassificationCategory
    confidence: int = Field(ge=0, le=100)
    explanation: str = Field(min_length=1)
    evidence_transaction_ids: list[str] = Field(default_factory=list)
    requires_human_review: bool = True


class ExceptionClassifier(Protocol):
    name: str
    prompt_version: str

    def classify(self, evidence_pack: dict) -> ExceptionClassification: ...


def _failure(
    category: ClassificationCategory,
    explanation: str,
    evidence_pack: dict,
) -> ExceptionClassification:
    bank = evidence_pack.get("bank_transaction", {}) or {}
    ids = [str(bank.get("transaction_id"))] if bank.get("transaction_id") else []
    return ExceptionClassification(
        category=category,
        confidence=0,
        explanation=explanation[:500],
        evidence_transaction_ids=ids,
        requires_human_review=True,
    )


class FakeExceptionClassifier:
    name = "fake"
    prompt_version = PROMPT_VERSION_FAKE

    def classify(self, evidence_pack: dict) -> ExceptionClassification:
        reason_code = str(evidence_pack.get("reason_code") or "")
        bank = evidence_pack.get("bank_transaction") or {}
        related = evidence_pack.get("related_settlements") or []
        utr = str(bank.get("normalized_utr") or "")
        evidence_ids = [str(bank.get("transaction_id"))] + [
            str(s.get("transaction_id")) for s in related
        ]
        evidence_ids = [i for i in evidence_ids if i and i != "None"]

        if reason_code == "MULTIPLE_SETTLEMENT_CANDIDATES":
            return ExceptionClassification(
                category=ClassificationCategory.DUPLICATE_UTR,
                confidence=95,
                explanation=(
                    f"Normalized UTR {utr} appears on {len(related)} settlements; "
                    "deterministic matching refused to auto-match non-unique candidates."
                ),
                evidence_transaction_ids=evidence_ids,
                requires_human_review=True,
            )

        if reason_code == "NO_CANDIDATE":
            return ExceptionClassification(
                category=ClassificationCategory.UNRECOGNIZED_CREDIT,
                confidence=80,
                explanation=(
                    f"Bank credit {bank.get('external_id')} of "
                    f"{bank.get('amount_paise')} paise has no settlement or ledger "
                    "candidate; source of funds is unidentified."
                ),
                evidence_transaction_ids=evidence_ids,
                requires_human_review=True,
            )

        if related:
            nearest = min(related, key=lambda s: abs(int(s["amount_paise"]) - int(bank["amount_paise"])))
            delta = int(nearest["amount_paise"]) - int(bank["amount_paise"])
            if delta > 0:
                return ExceptionClassification(
                    category=ClassificationCategory.REFUND_LAG,
                    confidence=75,
                    explanation=(
                        f"Settlement {nearest['external_id']} exceeds the bank credit by "
                        f"{delta} paise, consistent with a partial refund not yet settled."
                    ),
                    evidence_transaction_ids=evidence_ids,
                    requires_human_review=True,
                )

        return ExceptionClassification(
            category=ClassificationCategory.AMBIGUOUS_MATCH,
            confidence=60,
            explanation="Deterministic strategies could not resolve this residue uniquely.",
            evidence_transaction_ids=evidence_ids,
            requires_human_review=True,
        )


class ProviderError(Exception):
    pass


GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = (
    "You are a finance reconciliation assistant. You classify one unresolved "
    "exception at a time using only the facts provided. Respond with strict JSON "
    "only; no prose before or after."
)

PROMPT_TEMPLATE = """Classify the reconciliation exception described below.

Return ONLY a JSON object with exactly these keys:
{"category": "<one allowed category>", "confidence": <integer 0-100>,
 "explanation": "<one paragraph>", "evidence_transaction_ids": ["..."],
 "requires_human_review": true}

Allowed categories: $allowed_categories

Facts about the exception (JSON):
$exception_facts

Rules:
- Use only the facts above; never invent transaction ids or amounts.
- Cite only transaction ids present in the facts.
- Always set requires_human_review to true.
"""


class GroqExceptionClassifier:
    name = "groq"
    prompt_version = PROMPT_VERSION_GROQ

    def __init__(self, api_key: str, model: str, transport=None):
        self.api_key = api_key
        self.model = model
        if transport is not None:
            self._transport = transport
        else:
            self._transport = self._http_transport

    @property
    def full_name(self) -> str:
        return f"groq:{self.model}"

    def render_prompt(self, evidence_pack: dict) -> tuple[str, str]:
        user_prompt = PROMPT_TEMPLATE.replace(
            "$allowed_categories", ", ".join(ALLOWED_CATEGORIES)
        ).replace("$exception_facts", json.dumps(evidence_pack, default=str))
        if "$allowed_categories" in user_prompt or "$exception_facts" in user_prompt:
            raise ValueError("prompt template has unsubstituted placeholders")
        return SYSTEM_PROMPT, user_prompt

    def _http_transport(self, messages: list[dict[str, str]]) -> str:
        import httpx

        try:
            response = httpx.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                },
                timeout=30,
            )
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ProviderError(f"provider unreachable: {exc}") from exc
        except Exception as exc:
            raise ProviderError(f"provider call failed: {exc}") from exc
        if response.status_code in (429, 500, 502, 503, 504):
            raise ProviderError(f"provider transient error {response.status_code}")
        if response.status_code != 200:
            raise RuntimeError(f"provider rejected request: {response.status_code}")
        try:
            return response.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            raise ProviderError(f"malformed provider envelope: {exc}") from exc

    def _send_with_retry(self, messages: list[dict[str, str]]) -> tuple[str, int]:
        attempts = 0
        last_error: Exception | None = None
        for _ in range(2):
            attempts += 1
            try:
                return self._transport(messages), attempts
            except RuntimeError as exc:
                raise RuntimeError(str(exc)) from exc
            except ProviderError as exc:
                last_error = exc
        raise ProviderError(f"provider failed after {attempts} attempt(s): {last_error}")

    def _parse_content(self, content: str) -> ExceptionClassification | None:
        try:
            data = json.loads(content)
            return ExceptionClassification.model_validate(data)
        except (json.JSONDecodeError, ValidationError):
            return None

    def _sanitize(self, classification: ExceptionClassification) -> ExceptionClassification:
        data = classification.model_dump()
        data["requires_human_review"] = True
        return ExceptionClassification.model_validate(data)

    def classify(self, evidence_pack: dict) -> ExceptionClassification:
        system_prompt, user_prompt = self.render_prompt(evidence_pack)
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            content, _ = self._send_with_retry(messages)
        except (ProviderError, RuntimeError) as exc:
            return _failure(ClassificationCategory.MODEL_UNAVAILABLE, str(exc), evidence_pack)

        classification = self._parse_content(content)
        if classification is None:
            repair_messages = messages + [
                {
                    "role": "assistant",
                    "content": content[:2000],
                },
                {
                    "role": "user",
                    "content": "That was not valid JSON for the required schema. "
                    "Return only the corrected JSON object.",
                },
            ]
            try:
                content, _ = self._send_with_retry(repair_messages)
            except ProviderError as exc:
                return _failure(
                    ClassificationCategory.INVALID_MODEL_OUTPUT,
                    f"repair attempt failed: {exc}",
                    evidence_pack,
                )
            classification = self._parse_content(content)
            if classification is None:
                return _failure(
                    ClassificationCategory.INVALID_MODEL_OUTPUT,
                    "model output was not schema-valid JSON after one repair retry",
                    evidence_pack,
                )

        return self._sanitize(classification)


def get_classifier(settings: Any, use_ai: bool = False) -> ExceptionClassifier:
    if use_ai and getattr(settings, "groq_api_key", "") and getattr(settings, "groq_model", ""):
        return GroqExceptionClassifier(
            api_key=settings.groq_api_key, model=settings.groq_model
        )
    return FakeExceptionClassifier()


__all__ = [
    "ALLOWED_CATEGORIES",
    "ClassificationCategory",
    "ExceptionClassifier",
    "ExceptionClassification",
    "FakeExceptionClassifier",
    "GroqExceptionClassifier",
    "ProviderError",
    "ValidationError",
    "get_classifier",
]

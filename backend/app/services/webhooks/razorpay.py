from __future__ import annotations

import hashlib
import hmac

from fastapi import Request

SETTLEMENT_PROCESSED_EVENT = "settlement.processed"


class WebhookValidationError(Exception):
    pass


def compute_webhook_signature(raw_body: bytes, secret: str) -> str:
    return hmac.new(
        secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()


async def validate_razorpay_webhook(request: Request, secret: str) -> bytes:
    raw_body = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    if not secret:
        raise WebhookValidationError("webhook secret is not configured")
    if not signature:
        raise WebhookValidationError("missing x-razorpay-signature header")
    expected = compute_webhook_signature(raw_body, secret)
    if not hmac.compare_digest(expected, signature):
        raise WebhookValidationError("invalid webhook signature")
    return raw_body

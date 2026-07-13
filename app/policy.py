from __future__ import annotations

import re

from .models import RiskLevel

CARD_NUMBER = re.compile(r"\b(?:\d[ -]?){13,19}\b")
ACCOUNT_SECRET = re.compile(r"\b(?:password|passcode|one[- ]time code|otp|cvv|security code)\b", re.IGNORECASE)
SECRET_VALUE = re.compile(
    r"\b(password|passcode|one[- ]time code|otp|cvv|security code)\s*(?:is|:)?\s*([A-Za-z0-9!@#$%^&*._-]{3,})",
    re.IGNORECASE,
)
HIGH_IMPACT = re.compile(r"\b(?:cancel|refund|chargeback|fraud|dispute|close my account|change my plan)\b", re.IGNORECASE)


class PolicyViolation(ValueError):
    pass


def redact_sensitive_text(text: str) -> tuple[str, bool]:
    text, card_redacted = CARD_NUMBER.subn("[payment-card-redacted]", text)
    text, secret_redacted = SECRET_VALUE.subn(lambda match: f"{match.group(1)} [secret-redacted]", text)
    return text, bool(card_redacted or secret_redacted)


def assess_risk(text: str) -> tuple[RiskLevel, bool, str | None]:
    if CARD_NUMBER.search(text):
        return RiskLevel.HIGH, True, "Payment-card data detected; the caller must use the approved secure payment flow."
    if ACCOUNT_SECRET.search(text):
        return RiskLevel.HIGH, True, "Authentication secret detected; a verified human support path is required."
    if HIGH_IMPACT.search(text):
        return RiskLevel.HIGH, True, "The requested account or financial action requires supervisor approval."
    return RiskLevel.LOW, False, None


def assert_approval_allowed(roles: set[str]) -> None:
    if not ({"voiceops_supervisor", "voiceops_admin"} & roles):
        raise PolicyViolation("A VoiceOps supervisor or administrator role is required for approval.")

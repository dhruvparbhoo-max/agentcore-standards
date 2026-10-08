"""Local policy version 1.0.0.

Injection and secret-shaped text are blocked. Email, phone, and national-id
shapes are redacted. The matched text is not copied into the reason.
"""

from __future__ import annotations

import re

from agentcore_guardrails.decision import Blocked, Sanitized

_MAX_CHARS = 8_000
_INJECTION = (
    "ignore previous instructions",
    "disregard the system prompt",
    "reveal the system prompt",
)
_SECRET = re.compile(r"AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE = re.compile(r"\b(?:\+?\d[\d().\-\s]{7,}\d)\b")
_NATIONAL_ID = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def screen_text(text: str) -> Sanitized | Blocked:
    """Apply the local policy. Empty and over-long text are blocked."""
    if not isinstance(text, str) or not text.strip():
        return Blocked("empty")
    if len(text) > _MAX_CHARS:
        return Blocked("too_long")
    folded = text.casefold()
    if any(phrase in folded for phrase in _INJECTION):
        return Blocked("prompt_injection")
    if _SECRET.search(text):
        return Blocked("secret_material")
    redactions: list[str] = []
    cleaned = text
    cleaned, email_hits = _redact(cleaned, _EMAIL, "[redacted-email]")
    cleaned, phone_hits = _redact(cleaned, _PHONE, "[redacted-phone]")
    cleaned, id_hits = _redact(cleaned, _NATIONAL_ID, "[redacted-national-id]")
    if email_hits:
        redactions.append("email")
    if phone_hits:
        redactions.append("phone")
    if id_hits:
        redactions.append("national-id")
    return Sanitized(cleaned, tuple(redactions))


def _redact(text: str, pattern: re.Pattern[str], token: str) -> tuple[str, int]:
    hits = len(pattern.findall(text))
    if hits == 0:
        return text, 0
    return pattern.sub(token, text), hits

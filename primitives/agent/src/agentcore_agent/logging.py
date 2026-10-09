"""One JSON line per log record, with session and user ids on every line.

Copied from ``StructuredJsonFormatter``, ``CorrelatedLogger``, and
``update_correlation`` in awslabs/amazon-bedrock-agentcore-samples
(``05-autonomous-coding-agent-durable/shared/logging.py``, Apache-2.0). Changes:
``ticket_id`` became ``user_id``; the session id is hashed the same way as the
turn span; prompt and reply fields are dropped; text runs through the guardrail
redaction before it is written. See docs/attribution/third-party.md.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import MutableMapping
from typing import Any

from agentcore_guardrails import Blocked
from agentcore_guardrails.policy import screen_text
from agentcore_tracing import hash_session_id

PROMPT_FIELDS = frozenset(
    {"prompt", "completion", "reply", "messages", "system_prompt", "input", "output", "content", "arguments"}
)
_KNOWN_FIELDS = ("action", "tool", "decision", "duration_ms", "error", "release_id", "status")


def mask(text: str) -> str:
    """Redact emails, keys, and other PII patterns. Text the guard blocks is withheld."""
    screened = screen_text(text)
    if isinstance(screened, Blocked):
        return f"[withheld:{screened.reason}]"
    return screened.text


class StructuredJsonFormatter(logging.Formatter):
    """Format log records as single-line JSON for CloudWatch ingestion."""

    def __init__(self, component: str = "unknown", session_id: str = "", user_id: str = "") -> None:
        super().__init__()
        self.component = component
        self.session_id = session_id
        self.user_id = user_id

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "component": self.component,
            "logger": record.name,
            "message": mask(record.getMessage()),
            "session_id": hash_session_id(self.session_id) if self.session_id else "",
            "user_id": self.user_id,
        }
        for key in _KNOWN_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                entry[key] = _clean(value)
        extra = getattr(record, "_extra", None)
        if isinstance(extra, dict):
            entry.update({key: _clean(value) for key, value in extra.items() if key not in PROMPT_FIELDS})
        if record.exc_info and record.exc_info[0]:
            entry["exception"] = mask(self.formatException(record.exc_info))
        return json.dumps(entry, default=str)


class CorrelatedLogger(logging.LoggerAdapter[logging.Logger]):
    """Logger adapter that passes ``extra=`` through to the formatter."""

    def process(self, msg: Any, kwargs: MutableMapping[str, Any]) -> tuple[Any, MutableMapping[str, Any]]:
        extra = kwargs.get("extra", {})
        if extra:
            kwargs["extra"] = {"_extra": dict(extra)}
        return msg, kwargs


def get_logger(
    name: str,
    component: str | None = None,
    session_id: str = "",
    user_id: str = "",
    level: int = logging.INFO,
) -> CorrelatedLogger:
    if component is None:
        component = os.environ.get("AGENTCORE_PATTERN", "unknown")
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredJsonFormatter(component=component, session_id=session_id, user_id=user_id))
        logger.addHandler(handler)
        logger.propagate = False
    return CorrelatedLogger(logger, {})


def update_correlation(logger: CorrelatedLogger, session_id: str = "", user_id: str = "") -> None:
    """Set the ids once the session and caller are known."""
    for handler in logger.logger.handlers:
        if isinstance(handler.formatter, StructuredJsonFormatter):
            if session_id:
                handler.formatter.session_id = session_id
            if user_id:
                handler.formatter.user_id = user_id


def _clean(value: Any) -> Any:
    return mask(value) if isinstance(value, str) else value

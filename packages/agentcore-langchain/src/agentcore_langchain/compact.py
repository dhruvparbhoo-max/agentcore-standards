"""Deterministic context compaction.

The system prompt stays the prefix. Bulky tool JSON is replaced with a stable
preview that keeps ids, amounts, status, and error codes. A state bar is
computed from tool names and error codes. It does not copy tool text, and it
does not call a model.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import SystemMessage

_KEEP = (
    "amount",
    "currency",
    "customer",
    "duplicate",
    "error",
    "idempotency_key",
    "invoice_id",
    "ok",
    "requested_by",
    "retryable",
    "status",
    "tenant_id",
)
_BAR_START = "<agent_status>"
_BAR_END = "</agent_status>"


def compact_tool_result(text: str, *, max_chars: int = 480) -> str:
    """Return ``text`` unchanged when it fits. Otherwise a stable JSON preview.

    The same input always yields the same output. Amounts and error codes are
    kept. A long note is shortened, then dropped, before the raw string is cut.
    """
    if max_chars < 16:
        raise ValueError("max_chars must be at least 16")
    if len(text) <= max_chars:
        return text
    preview = _json_preview(text)
    if preview is not None and len(preview) <= max_chars:
        return preview
    marker = "<compacted/>"
    room = max_chars - len(marker)
    return text[:room] + marker


def render_state_bar(messages: Sequence[Any]) -> str:
    """One status block from tool names and error codes. Not a copy of tool text."""
    counts: dict[str, int] = {}
    last_error = "none"
    for message in messages:
        name = getattr(message, "name", None)
        content = getattr(message, "content", None)
        if getattr(message, "type", None) != "tool" and not _is_tool_message(message):
            continue
        if isinstance(name, str) and name:
            counts[name] = counts.get(name, 0) + 1
        code = _error_code(content)
        if code is not None:
            last_error = code
    lines = [_BAR_START]
    for name in sorted(counts):
        lines.append(f"tool_count.{name}={counts[name]}")
    lines.append(f"last_error={last_error}")
    lines.append(_BAR_END)
    return "\n".join(lines)


def is_state_bar(text: str) -> bool:
    """True when ``text`` is a bar this module rendered."""
    stripped = text.strip()
    return stripped.startswith(_BAR_START) and stripped.endswith(_BAR_END)


class CompactTrajectoryMiddleware(AgentMiddleware):
    """Shorten oversized tool results and show the model a code-built status bar.

    The bar is added to the model request. It is not written into the system
    prompt and it is not a user message. This middleware is innermost so PII
    redaction has already run.
    """

    tools: Sequence[Any] = ()

    def __init__(self, *, max_chars: int = 480) -> None:
        self.max_chars = max_chars

    def wrap_tool_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return _compact_tool_message(handler(request), max_chars=self.max_chars)

    async def awrap_tool_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        return _compact_tool_message(await handler(request), max_chars=self.max_chars)

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return handler(_with_state_bar(request))

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        return await handler(_with_state_bar(request))


def _compact_tool_message(result: Any, *, max_chars: int) -> Any:
    content = getattr(result, "content", None)
    if not isinstance(content, str):
        return result
    compacted = compact_tool_result(content, max_chars=max_chars)
    if compacted == content or not hasattr(result, "model_copy"):
        return result
    return result.model_copy(update={"content": compacted})


def _with_state_bar(request: Any) -> Any:
    messages = list(getattr(request, "messages", ()) or ())
    status = SystemMessage(content=render_state_bar(messages))
    if messages and _message_text(messages[-1]).strip().startswith(_BAR_START):
        messages[-1] = status
    else:
        messages.append(status)
    if hasattr(request, "override"):
        return request.override(messages=messages)
    return request


def _json_preview(text: str) -> str | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    kept: dict[str, Any] = {key: parsed[key] for key in _KEEP if key in parsed}
    note = parsed.get("note")
    if isinstance(note, str) and note:
        kept["note"] = note[:80]
    kept["compacted"] = True
    encoded = json.dumps(kept, sort_keys=True)
    if len(encoded) <= 480:
        return encoded
    kept.pop("note", None)
    return json.dumps(kept, sort_keys=True)


def _error_code(content: object) -> str | None:
    if not isinstance(content, str):
        return None
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, Mapping):
        return None
    if parsed.get("ok") is True:
        return None
    code = parsed.get("error")
    if isinstance(code, str) and code and len(code) <= 64 and " " not in code:
        return code
    return None


def _is_tool_message(message: Any) -> bool:
    return type(message).__name__ == "ToolMessage"


def _message_text(message: Any) -> str:
    content = getattr(message, "content", "")
    return content if isinstance(content, str) else ""

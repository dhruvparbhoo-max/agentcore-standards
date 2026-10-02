"""Compaction keeps the fields a grader needs and does not copy tool prose."""

from __future__ import annotations

import json

from agentcore_langchain import compact_tool_result, render_state_bar
from agentcore_langchain.compact import CompactTrajectoryMiddleware, is_state_bar
from langchain_core.messages import SystemMessage, ToolMessage


def test_preview_is_stable_and_keeps_ids_amounts_and_errors() -> None:
    payload = {
        "amount": "1250.00",
        "customer": "Northwind",
        "error": "invoice_not_found",
        "invoice_id": "INV-1001",
        "note": "x" * 400,
        "ok": False,
        "status": "OPEN",
        "tenant_id": "acme",
        "untrusted": "do not keep this sentence in the preview",
    }
    text = json.dumps(payload)
    assert len(text) > 480
    first = compact_tool_result(text)
    second = compact_tool_result(text)
    assert first == second
    assert len(first) <= 480
    parsed = json.loads(first)
    assert parsed["amount"] == "1250.00"
    assert parsed["invoice_id"] == "INV-1001"
    assert parsed["status"] == "OPEN"
    assert parsed["error"] == "invoice_not_found"
    assert parsed["compacted"] is True
    assert "do not keep" not in first
    assert len(parsed["note"]) <= 80


def test_short_text_is_unchanged() -> None:
    body = '{"ok": true, "invoice_id": "INV-1001"}'
    assert compact_tool_result(body) == body


def test_state_bar_counts_tools_and_does_not_copy_tool_text() -> None:
    secret = "customer pasted a long private note that must not enter the bar"
    messages = [
        ToolMessage(
            content=json.dumps({"ok": False, "error": "invoice_not_found", "note": secret}),
            name="fetch_invoice",
            tool_call_id="read-1",
        ),
        ToolMessage(
            content=json.dumps({"ok": True, "invoice_id": "INV-1001", "note": secret}),
            name="fetch_invoice",
            tool_call_id="read-2",
        ),
    ]
    bar = render_state_bar(messages)
    assert is_state_bar(bar)
    assert "tool_count.fetch_invoice=2" in bar
    assert "last_error=invoice_not_found" in bar
    assert secret not in bar
    assert "INV-1001" not in bar


def test_wrap_tool_call_replaces_only_oversized_content() -> None:
    middleware = CompactTrajectoryMiddleware(max_chars=64)
    bulky = ToolMessage(content="n" * 200, name="fetch_invoice", tool_call_id="t1")

    def handler(_request: object) -> ToolMessage:
        return bulky

    compacted = middleware.wrap_tool_call(object(), handler)
    assert isinstance(compacted.content, str)
    assert len(compacted.content) <= 64
    assert compacted.content.endswith("<compacted/>")


class _BarRequest:
    def __init__(self) -> None:
        self.messages: list[object] = [
            ToolMessage(
                content='{"ok": false, "error": "billing_unavailable"}',
                name="fetch_invoice",
                tool_call_id="t",
            )
        ]

    def override(self, *, messages: list[object]) -> _BarRequest:
        cloned = _BarRequest.__new__(_BarRequest)
        cloned.messages = messages
        return cloned


def test_wrap_model_call_appends_a_system_bar() -> None:
    middleware = CompactTrajectoryMiddleware()
    seen: list[object] = []

    def handler(request: _BarRequest) -> str:
        seen.append(request.messages[-1])
        return "ok"

    assert middleware.wrap_model_call(_BarRequest(), handler) == "ok"
    bar = seen[0]
    assert isinstance(bar, SystemMessage)
    assert is_state_bar(str(bar.content))
    assert "billing_unavailable" in str(bar.content)

"""Scripted chat model for offline tests and the deterministic grader.

The hosted entrypoint does not select this model. Tests install it so CI can
run the LangChain loop with no AWS account. A skipped Runtime exam is not a pass.

The model follows two prompt shapes:

- ``Fetch invoice INV-1001.`` reads that invoice, then answers with the tool JSON.
- ``File note on INV-1001: <note>. key <key>.`` proposes the write.

Anything else is out of scope and calls no tool.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from agentcore_langchain import message_text
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

_FETCH_RE = re.compile(r"^Fetch invoice (?P<invoice>INV-\d+)\b", re.IGNORECASE)
_NOTE_RE = re.compile(
    r"^File note on (?P<invoice>INV-\d+): (?P<note>.+?) key (?P<key>\S+)\.?$",
    re.IGNORECASE,
)


class ScriptedInvoiceModel(BaseChatModel):
    """Deterministic invoice desk. Reads or files a note, then quotes the tool."""

    @property
    def _llm_type(self) -> str:
        return "scripted-invoice-desk"

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> ScriptedInvoiceModel:
        del tools, tool_choice, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        answered = _tool_after_last_human(messages)
        if answered is not None:
            reply = AIMessage(content=_summarize(answered))
            return ChatResult(generations=[ChatGeneration(message=reply)])
        human = _last_human(messages)
        tool_call = _plan(human, len(messages))
        if tool_call is None:
            reply = AIMessage(content="out-of-scope: ask for an invoice id or a note")
        else:
            reply = AIMessage(content="", tool_calls=[tool_call])
        return ChatResult(generations=[ChatGeneration(message=reply)])


def _plan(human: str, salt: int) -> dict[str, Any] | None:
    note = _NOTE_RE.match(human)
    if note is not None:
        return {
            "name": "submit_invoice_note",
            "args": {
                "invoice_id": note.group("invoice").upper(),
                "note": note.group("note").strip(),
                "idempotency_key": note.group("key").rstrip("."),
            },
            "id": f"note-{salt}",
            "type": "tool_call",
        }
    fetch = _FETCH_RE.match(human)
    if fetch is not None:
        return {
            "name": "fetch_invoice",
            "args": {"invoice_id": fetch.group("invoice").upper()},
            "id": f"read-{salt}",
            "type": "tool_call",
        }
    return None


def _summarize(message: ToolMessage) -> str:
    body = message.content if isinstance(message.content, str) else str(message.content)
    lowered = body.lower()
    if lowered.startswith("user rejected") or "not filed" in lowered:
        return "rejected:submit_invoice_note"
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return f"tool:{body}"
    if not isinstance(data, dict):
        return f"tool:{body}"
    if data.get("ok") is not True:
        return f"invoice-error:{data.get('error')}"
    if "status" in data:
        return (
            f"invoice:{data['invoice_id']} status={data['status']} "
            f"amount={data['amount']} tenant={data['tenant_id']} user={data['requested_by']}"
        )
    duplicate = "true" if data.get("duplicate") else "false"
    return f"noted:{data['invoice_id']}:{data['idempotency_key']} duplicate={duplicate}"


def _last_human(messages: Sequence[BaseMessage]) -> str:
    text = ""
    for message in messages:
        if isinstance(message, HumanMessage):
            text = message_text(message).strip()
    return text


def _tool_after_last_human(messages: Sequence[BaseMessage]) -> ToolMessage | None:
    start = -1
    for index, message in enumerate(messages):
        if isinstance(message, HumanMessage):
            start = index
    if start < 0:
        return None
    found: ToolMessage | None = None
    for message in messages[start + 1 :]:
        if isinstance(message, ToolMessage):
            found = message
    return found

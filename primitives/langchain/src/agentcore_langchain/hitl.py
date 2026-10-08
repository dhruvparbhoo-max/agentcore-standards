"""Human approval for side-effecting LangChain tools.

Reads are listed as auto-approved. Writes allow ``approve`` and ``reject``.
``edit`` can change an idempotency key. ``respond`` would look like success.
Rejection is a tool result the model can read. The eval-pack ``HitlGate`` is a
different interface and stays in ``agentcore-eval``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    ModelCallLimitMiddleware,
    ModelRetryMiddleware,
    PIIMiddleware,
    ToolCallLimitMiddleware,
    ToolRetryMiddleware,
)

from agentcore_langchain.compact import CompactTrajectoryMiddleware

_WRITE_DECISIONS = ["approve", "reject"]
_THREAD_MODEL_CALLS = 24
_RUN_MODEL_CALLS = 8
_RETRIES = 2


def agent_middleware(
    *,
    write_tools: Mapping[str, str],
    read_tools: Sequence[str] = (),
    retry_on: tuple[type[Exception], ...] = (TimeoutError, ConnectionError),
    before_redaction: Sequence[Any] = (),
) -> list[Any]:
    """Middleware stack. The first entry is outermost. Approval is that gate.

    ``write_tools`` maps a tool name to the sentence a reviewer sees. ``read_tools``
    are explicit auto-approvals. ``before_redaction`` runs after the retry
    limiters and before PII redaction, so a shelf guard can screen text first.
    Compaction does not call a model.
    """
    if not write_tools:
        raise ValueError("at least one write tool is required")
    limiters: list[Any] = [ToolCallLimitMiddleware(thread_limit=20, run_limit=10)]
    for name in write_tools:
        limiters.append(
            ToolCallLimitMiddleware(
                tool_name=name,
                thread_limit=6,
                run_limit=4,
                exit_behavior="continue",
            )
        )
    # First entry is the outermost wrapper. Approval therefore runs before a
    # retry or the tool handler. PII redacts before compaction sees the text.
    return [
        approval_middleware(write_tools=write_tools, read_tools=read_tools),
        *limiters,
        ToolRetryMiddleware(
            max_retries=_RETRIES,
            retry_on=retry_on,
            on_failure="continue",
            initial_delay=0.0,
            jitter=False,
        ),
        ModelRetryMiddleware(
            max_retries=_RETRIES,
            retry_on=(TimeoutError, ConnectionError),
            on_failure="error",
            initial_delay=0.0,
            jitter=False,
        ),
        ModelCallLimitMiddleware(
            thread_limit=_THREAD_MODEL_CALLS,
            run_limit=_RUN_MODEL_CALLS,
            exit_behavior="end",
        ),
        *before_redaction,
        PIIMiddleware(
            "email",
            strategy="redact",
            apply_to_input=True,
            apply_to_output=True,
            apply_to_tool_results=True,
        ),
        PIIMiddleware(
            "credit_card",
            strategy="mask",
            apply_to_input=True,
            apply_to_output=True,
            apply_to_tool_results=True,
        ),
        CompactTrajectoryMiddleware(),
    ]


def approval_middleware(
    *,
    write_tools: Mapping[str, str],
    read_tools: Sequence[str] = (),
) -> HumanInTheLoopMiddleware:
    """Pause named write tools. Unlisted tools stay auto-approved."""
    interrupt_on: dict[str, Any] = {name: False for name in read_tools}
    for name, description in write_tools.items():
        if not description.strip():
            raise ValueError("write tool description is required")
        interrupt_on[name] = {
            "allowed_decisions": list(_WRITE_DECISIONS),
            "description": description.strip(),
        }
    return HumanInTheLoopMiddleware(
        interrupt_on=interrupt_on,
        description_prefix="Tool execution needs approval",
    )


def parse_approval(raw: Any, *, reject_message: str) -> dict[str, Any] | None:
    """Parse one approve or reject decision. ``None`` means this is not a resume.

    ``edit`` and ``respond`` raise ``ValueError``. A reject with no message uses
    ``reject_message`` so the model is told the tool did not run.
    """
    if raw is None:
        return None
    if not reject_message.strip():
        raise ValueError("reject_message is required")
    if isinstance(raw, str):
        choice = raw.strip().lower()
        if choice not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        if choice == "reject":
            return {"message": reject_message, "type": "reject"}
        return {"type": "approve"}
    if isinstance(raw, Mapping):
        choice_raw = raw.get("type")
        if not isinstance(choice_raw, str) or choice_raw not in {"approve", "reject"}:
            raise ValueError("decision must be approve or reject")
        if choice_raw == "approve":
            return {"type": "approve"}
        message = raw.get("message")
        if message is None:
            return {"message": reject_message, "type": "reject"}
        if isinstance(message, str) and message.strip():
            return {"message": message.strip(), "type": "reject"}
        raise ValueError("decision message must be a string")
    raise ValueError("decision must be approve or reject")


def interrupt_view(interrupt: Any) -> dict[str, Any]:
    """Tool name, arguments, and allowed decisions from one interrupt value."""
    value = getattr(interrupt, "value", interrupt)
    if not isinstance(value, Mapping):
        return {"allowed_decisions": list(_WRITE_DECISIONS), "arguments": {}, "tool": None}
    actions = value.get("action_requests") or []
    action = actions[0] if isinstance(actions, list) and actions else {}
    if not isinstance(action, Mapping):
        action = {}
    reviews = value.get("review_configs") or []
    review = reviews[0] if isinstance(reviews, list) and reviews else {}
    allowed = list(_WRITE_DECISIONS)
    if isinstance(review, Mapping):
        listed = review.get("allowed_decisions")
        if isinstance(listed, list) and listed:
            allowed = [str(item) for item in listed]
    arguments = action.get("args") if isinstance(action.get("args"), dict) else action.get("arguments")
    if not isinstance(arguments, dict):
        arguments = {}
    tool_name = action.get("name")
    return {
        "allowed_decisions": allowed,
        "arguments": arguments,
        "tool": tool_name if isinstance(tool_name, str) else None,
    }

"""Connect a paused write to ApprovalGate.

The token is issued when the graph interrupts and consumed inside the write
tool. The actor on the token cannot be the approver.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from agentcore_approvals import ApprovalError, ApprovalGate
from agentcore_tools.idempotency import args_hash

_gate = ApprovalGate()
_pending: dict[str, str] = {}
_ready: dict[str, tuple[str, str, str]] = {}


def reset_approvals() -> None:
    """Drop process-local tokens. Tests call this between cases."""
    global _gate
    _gate = ApprovalGate()
    _pending.clear()
    _ready.clear()


def note_arguments(arguments: dict[str, Any]) -> dict[str, str]:
    """The three fields the write tool and the interrupt must hash the same way."""
    invoice_id = arguments.get("invoice_id")
    note = arguments.get("note")
    key = arguments.get("idempotency_key")
    if not isinstance(invoice_id, str) or not isinstance(note, str) or not isinstance(key, str):
        raise ApprovalError("mismatch")
    cleaned = {
        "idempotency_key": key.strip(),
        "invoice_id": invoice_id.strip(),
        "note": note.strip(),
    }
    if not all(cleaned.values()):
        raise ApprovalError("mismatch")
    return cleaned


def issue_for_interrupt(
    *,
    session_id: str,
    actor_id: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> str:
    """Open a token for this session. A later resume decides it."""
    canonical = note_arguments(arguments)
    token = _gate.issue(
        tool_name=tool_name,
        args_hash=args_hash(canonical),
        actor_id=actor_id,
        ttl_seconds=3600,
        now=datetime.now(UTC),
    )
    _pending[session_id] = token
    _ready[session_id] = (token, tool_name, args_hash(canonical))
    return token


def settle(*, session_id: str, approver_id: str, approved: bool) -> None:
    """Record the reviewer's decision. Rejection drops the token."""
    token = _pending.get(session_id)
    if token is None:
        raise ApprovalError("unknown_token")
    _gate.decide(
        token,
        approved=approved,
        approver_id=approver_id,
        now=datetime.now(UTC),
    )
    if not approved:
        _pending.pop(session_id, None)
        _ready.pop(session_id, None)


def consume_write(
    *,
    session_id: str,
    actor_id: str,
    tool_name: str,
    arguments: dict[str, Any],
) -> None:
    """Spend the approved token before the registry write runs."""
    pending = _ready.get(session_id)
    if pending is None:
        raise ApprovalError("not_approved")
    token, expected_tool, digest = pending
    canonical = note_arguments(arguments)
    if expected_tool != tool_name or digest != args_hash(canonical):
        raise ApprovalError("mismatch")
    _gate.consume(
        token,
        tool_name=tool_name,
        args_hash=digest,
        actor_id=actor_id,
        now=datetime.now(UTC),
    )
    _pending.pop(session_id, None)
    _ready.pop(session_id, None)

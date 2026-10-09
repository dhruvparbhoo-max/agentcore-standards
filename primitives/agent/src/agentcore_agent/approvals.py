"""``pause_for_human``: one pause, one token, one expiry for every framework.

The token is bound to the tool name, the argument hash, and the actor. The
store is a protocol so the approval pattern can put it on a DynamoDB job row.
The in-memory store wraps ``agentcore_approvals.ApprovalGate``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from agentcore_approvals import ApprovalGate
from agentcore_tools.idempotency import args_hash


@dataclass(frozen=True)
class PauseRequest:
    """What a reviewer sees. A vague "approve?" is not enough."""

    tool: str
    arguments: Mapping[str, Any]
    actor_id: str
    action: str
    session_id: str
    reviewers: int
    expire_s: int
    summary: str = ""

    @property
    def args_hash(self) -> str:
        return args_hash(dict(self.arguments))


@dataclass(frozen=True)
class PauseTicket:
    token_id: str
    tool: str
    args_hash: str
    actor_id: str
    action: str
    reviewers: int
    expires_at: datetime
    arguments: Mapping[str, Any] = field(default_factory=dict)
    summary: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "token_id": self.token_id,
            "tool": self.tool,
            "args_hash": self.args_hash,
            "actor_id": self.actor_id,
            "action": self.action,
            "reviewers": self.reviewers,
            "expires_at": self.expires_at.isoformat(),
            "arguments": dict(self.arguments),
            "summary": self.summary,
        }


class ApprovalStore(Protocol):
    def open(self, request: PauseRequest, *, now: datetime) -> PauseTicket:
        """Record a pending approval and return its ticket."""

    def get(self, token_id: str) -> PauseTicket:
        """The ticket for ``token_id``. Raises ``KeyError`` when unknown."""

    def decide(self, token_id: str, *, approved: bool, approver_id: str, now: datetime) -> None:
        """Record a reviewer's decision. The reviewer must not be the actor."""

    def consume(self, token_id: str, *, tool: str, args_hash: str, actor_id: str, now: datetime) -> None:
        """Spend an approved token once, inside the tool handler."""


class InMemoryApprovalStore:
    """Process-local store. Good for tests and ``make local``; a job row replaces it in a deploy."""

    def __init__(self, gate: ApprovalGate | None = None) -> None:
        self.gate = gate if gate is not None else ApprovalGate()
        self.tickets: dict[str, PauseTicket] = {}

    def open(self, request: PauseRequest, *, now: datetime) -> PauseTicket:
        token_id = self.gate.issue(
            tool_name=request.tool,
            args_hash=request.args_hash,
            actor_id=request.actor_id,
            ttl_seconds=request.expire_s,
            now=now,
        )
        ticket = PauseTicket(
            token_id=token_id,
            tool=request.tool,
            args_hash=request.args_hash,
            actor_id=request.actor_id,
            action=request.action,
            reviewers=request.reviewers,
            expires_at=now + timedelta(seconds=request.expire_s),
            arguments=dict(request.arguments),
            summary=request.summary,
        )
        self.tickets[token_id] = ticket
        return ticket

    def get(self, token_id: str) -> PauseTicket:
        return self.tickets[token_id]

    def decide(self, token_id: str, *, approved: bool, approver_id: str, now: datetime) -> None:
        self.gate.decide(token_id, approved=approved, approver_id=approver_id, now=now)

    def consume(self, token_id: str, *, tool: str, args_hash: str, actor_id: str, now: datetime) -> None:
        self.gate.consume(token_id, tool_name=tool, args_hash=args_hash, actor_id=actor_id, now=now)


def utc_now() -> datetime:
    return datetime.now(UTC)

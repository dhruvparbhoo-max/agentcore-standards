"""Pending, approve, consume. Expired, rejected, and reused tokens do not proceed."""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta

_AWARE = "datetime must be timezone-aware"


class ApprovalError(Exception):
    """The token cannot authorize this call. ``code`` is the stable reason."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AuditRecord:
    """One gate transition. Arguments are not stored."""

    def __init__(self, *, token_id: str, action: str, actor_id: str, tool_name: str, at: datetime) -> None:
        self.token_id = token_id
        self.action = action
        self.actor_id = actor_id
        self.tool_name = tool_name
        self.at = at


class _Token:
    def __init__(
        self,
        *,
        token_id: str,
        tool_name: str,
        args_hash: str,
        actor_id: str,
        expires_at: datetime,
    ) -> None:
        self.token_id = token_id
        self.tool_name = tool_name
        self.args_hash = args_hash
        self.actor_id = actor_id
        self.expires_at = expires_at
        self.status = "pending"
        self.approver_id: str | None = None


class ApprovalGate:
    """Process-local approvals. Callers pass ``now`` so tests do not use the wall clock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: dict[str, _Token] = {}
        self._audit: list[AuditRecord] = []

    def issue(
        self,
        *,
        tool_name: str,
        args_hash: str,
        actor_id: str,
        ttl_seconds: int,
        now: datetime,
    ) -> str:
        """Open a pending token bound to the tool, the argument hash, and the actor."""
        _aware(now)
        _label(tool_name, "tool name")
        _label(args_hash, "args hash")
        _label(actor_id, "actor id")
        if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or ttl_seconds < 1 or ttl_seconds > 86_400:
            raise ValueError("ttl_seconds must be between 1 and 86400")
        token = _Token(
            token_id=str(uuid.uuid4()),
            tool_name=tool_name,
            args_hash=args_hash,
            actor_id=actor_id,
            expires_at=now + timedelta(seconds=ttl_seconds),
        )
        with self._lock:
            self._tokens[token.token_id] = token
            self._audit.append(
                AuditRecord(
                    token_id=token.token_id,
                    action="issue",
                    actor_id=actor_id,
                    tool_name=tool_name,
                    at=now,
                )
            )
        return token.token_id

    def decide(self, token_id: str, *, approved: bool, approver_id: str, now: datetime) -> None:
        """Record a decision. The approver must be a different party from the actor."""
        _aware(now)
        _label(approver_id, "approver id")
        with self._lock:
            token = self._need(token_id)
            if now >= token.expires_at:
                token.status = "expired"
                self._record(token, "expire", approver_id, now)
                raise ApprovalError("expired")
            if approver_id == token.actor_id:
                self._record(token, "reject-self", approver_id, now)
                raise ApprovalError("approver_is_actor")
            if token.status != "pending":
                raise ApprovalError("not_pending")
            token.status = "approved" if approved else "rejected"
            token.approver_id = approver_id
            self._record(token, token.status, approver_id, now)

    def consume(
        self,
        token_id: str,
        *,
        tool_name: str,
        args_hash: str,
        actor_id: str,
        now: datetime,
    ) -> None:
        """Spend an approved token once. A mismatch does not change the token to approved."""
        _aware(now)
        with self._lock:
            token = self._need(token_id)
            if now >= token.expires_at:
                token.status = "expired"
                self._record(token, "expire", actor_id, now)
                raise ApprovalError("expired")
            if token.status == "consumed":
                raise ApprovalError("consumed")
            if token.status != "approved":
                raise ApprovalError("not_approved")
            if token.tool_name != tool_name or token.args_hash != args_hash or token.actor_id != actor_id:
                self._record(token, "mismatch", actor_id, now)
                raise ApprovalError("mismatch")
            token.status = "consumed"
            self._record(token, "consume", actor_id, now)

    def audit(self) -> tuple[AuditRecord, ...]:
        """Return the transition log in order."""
        with self._lock:
            return tuple(self._audit)

    def _need(self, token_id: str) -> _Token:
        token = self._tokens.get(token_id)
        if token is None:
            raise ApprovalError("unknown_token")
        return token

    def _record(self, token: _Token, action: str, actor_id: str, now: datetime) -> None:
        self._audit.append(
            AuditRecord(
                token_id=token.token_id,
                action=action,
                actor_id=actor_id,
                tool_name=token.tool_name,
                at=now,
            )
        )


def _aware(value: datetime) -> None:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(_AWARE)


def _label(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"invalid {label}")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"invalid {label}")

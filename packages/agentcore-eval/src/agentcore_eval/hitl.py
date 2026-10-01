"""Human-in-the-loop approval gate used by evals.

High-risk actions stay blocked until a decision arrives, and a decision at or
after ``expires_at`` does not proceed. The human-in-the-loop template will call
this interface. This module is the eval stand-in, not that template.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from agentcore_eval.harness import RuntimeHarness
from agentcore_eval.model import Eval, EvalContext, Hook


class ApprovalStatus(StrEnum):
    """Lifecycle of one approval. ``EXPIRED`` wins over a stored decision."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


class Approval:
    """One approval record as observed at a specific ``now``."""

    def __init__(
        self,
        *,
        approval_id: str,
        action: str,
        subject: str,
        status: ApprovalStatus,
        expires_at: datetime,
    ) -> None:
        self.approval_id = approval_id
        self.action = action
        self.subject = subject
        self.status = status
        self.expires_at = expires_at


@runtime_checkable
class HitlGate(Protocol):
    """Pause a high-risk action until an unexpired approval exists."""

    def request(self, *, approval_id: str, action: str, subject: str, expires_at: datetime) -> Approval:
        """Open an approval. The action is pending until ``decide``."""

    def decide(self, approval_id: str, *, approved: bool, now: datetime) -> Approval:
        """Record a decision. A late decision leaves the approval expired."""

    def check(self, approval_id: str, *, now: datetime) -> Approval:
        """Return the status at ``now``. ``now >= expires_at`` is expired."""

    def allows(self, approval_id: str, *, now: datetime) -> bool:
        """Return whether the action may proceed at ``now``."""


class _Record:
    def __init__(self, *, approval_id: str, action: str, subject: str, expires_at: datetime) -> None:
        self.approval_id = approval_id
        self.action = action
        self.subject = subject
        self.expires_at = expires_at
        self.decision = ApprovalStatus.PENDING


class InMemoryHitlGate:
    """Process-local gate. Callers pass ``now`` so tests do not depend on the wall clock."""

    def __init__(self) -> None:
        self._records: dict[str, _Record] = {}

    def request(self, *, approval_id: str, action: str, subject: str, expires_at: datetime) -> Approval:
        _require_aware(expires_at, label="expires_at")
        if not approval_id or not action or not subject:
            raise ValueError("approval_id, action, and subject are required")
        if approval_id in self._records:
            raise ValueError(f"approval {approval_id} already exists")
        record = _Record(
            approval_id=approval_id,
            action=action,
            subject=subject,
            expires_at=expires_at,
        )
        self._records[approval_id] = record
        return Approval(
            approval_id=approval_id,
            action=action,
            subject=subject,
            status=ApprovalStatus.PENDING,
            expires_at=expires_at,
        )

    def decide(self, approval_id: str, *, approved: bool, now: datetime) -> Approval:
        record = self._require(approval_id)
        _require_aware(now, label="now")
        if now < record.expires_at:
            record.decision = ApprovalStatus.APPROVED if approved else ApprovalStatus.DENIED
        return self._view(record, now=now)

    def check(self, approval_id: str, *, now: datetime) -> Approval:
        _require_aware(now, label="now")
        return self._view(self._require(approval_id), now=now)

    def allows(self, approval_id: str, *, now: datetime) -> bool:
        return self.check(approval_id, now=now).status is ApprovalStatus.APPROVED

    def known(self, approval_id: str) -> bool:
        """Return whether ``request`` has already opened ``approval_id``."""
        return approval_id in self._records

    def _require(self, approval_id: str) -> _Record:
        record = self._records.get(approval_id)
        if record is None:
            raise ValueError(f"unknown approval {approval_id}")
        return record

    def _view(self, record: _Record, *, now: datetime) -> Approval:
        status = ApprovalStatus.EXPIRED if now >= record.expires_at else record.decision
        return Approval(
            approval_id=record.approval_id,
            action=record.action,
            subject=record.subject,
            status=status,
            expires_at=record.expires_at,
        )


def assert_blocked_without_approval(gate: HitlGate, approval_id: str, *, now: datetime) -> None:
    """The action is still pending and ``allows`` is false."""
    approval = gate.check(approval_id, now=now)
    if approval.status is not ApprovalStatus.PENDING:
        raise AssertionError(f"{approval_id}: expected pending, got {approval.status.value}")
    if gate.allows(approval_id, now=now):
        raise AssertionError(f"{approval_id}: proceeded without approval")


def assert_proceeds_with_approval(gate: HitlGate, approval_id: str, *, now: datetime) -> None:
    """An unexpired approval lets the action proceed."""
    approval = gate.check(approval_id, now=now)
    if approval.status is not ApprovalStatus.APPROVED:
        raise AssertionError(f"{approval_id}: expected approved, got {approval.status.value}")
    if not gate.allows(approval_id, now=now):
        raise AssertionError(f"{approval_id}: approved action did not proceed")


def assert_approval_expired(gate: HitlGate, approval_id: str, *, now: datetime) -> None:
    """``now >= expires_at`` blocks the action even if a decision was recorded."""
    approval = gate.check(approval_id, now=now)
    if approval.status is not ApprovalStatus.EXPIRED:
        raise AssertionError(f"{approval_id}: expected expired, got {approval.status.value}")
    if gate.allows(approval_id, now=now):
        raise AssertionError(f"{approval_id}: expired approval proceeded")


def hitl_evals() -> tuple[Eval, ...]:
    """Blocked, approved, and expired cases against ``InMemoryHitlGate``."""
    return (
        _eval("hitl.blocked-without-approval", "A requested payment stays pending until a decision.", _blocked),
        _eval("hitl.proceeds-with-approval", "A decision before expiry lets the payment proceed.", _proceeds),
        _eval("hitl.expired", "A decision at the expiry time does not let the payment proceed.", _expired),
    )


def _eval(name: str, rubric: str, assert_: Hook) -> Eval:
    def setup(harness: RuntimeHarness, ctx: EvalContext) -> None:
        ctx.session = harness.start(actor_id="actor-controller", agent_version=ctx.agent_version)

    def act(harness: RuntimeHarness, ctx: EvalContext) -> None:
        del harness, ctx

    return Eval(name=name, rubric=rubric, setup=setup, act=act, assert_=assert_)


def _blocked(harness: RuntimeHarness, ctx: EvalContext) -> None:
    del harness, ctx
    gate = InMemoryHitlGate()
    now = _at(12)
    gate.request(approval_id="apr-blocked", action="approve.payment", subject="INV-1042", expires_at=_at(13))
    assert_blocked_without_approval(gate, "apr-blocked", now=now)


def _proceeds(harness: RuntimeHarness, ctx: EvalContext) -> None:
    del harness, ctx
    gate = InMemoryHitlGate()
    now = _at(12)
    gate.request(approval_id="apr-ok", action="approve.payment", subject="INV-1042", expires_at=_at(13))
    gate.decide("apr-ok", approved=True, now=now)
    assert_proceeds_with_approval(gate, "apr-ok", now=now)


def _expired(harness: RuntimeHarness, ctx: EvalContext) -> None:
    del harness, ctx
    gate = InMemoryHitlGate()
    expires_at = _at(13)
    gate.request(approval_id="apr-exp", action="approve.payment", subject="INV-1042", expires_at=expires_at)
    gate.decide("apr-exp", approved=True, now=expires_at)
    assert_approval_expired(gate, "apr-exp", now=expires_at)


def _at(hour: int) -> datetime:
    return datetime(2026, 10, 1, hour, 0, tzinfo=UTC)


def _require_aware(value: datetime, *, label: str) -> None:
    if value.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")

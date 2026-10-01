"""Approval gate: pending, approved before expiry, and expired at the deadline."""

from datetime import UTC, datetime, timedelta

import pytest
from agentcore_eval import (
    ApprovalStatus,
    InMemoryHitlGate,
    assert_approval_expired,
    assert_blocked_without_approval,
    assert_proceeds_with_approval,
)


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, 1, hour, minute, tzinfo=UTC)


def test_blocked_until_approval() -> None:
    gate = InMemoryHitlGate()
    now = _at(12)
    gate.request(approval_id="apr-1", action="approve.payment", subject="INV-1042", expires_at=_at(13))
    assert_blocked_without_approval(gate, "apr-1", now=now)
    gate.decide("apr-1", approved=False, now=now)
    denied = gate.check("apr-1", now=now)
    assert denied.status is ApprovalStatus.DENIED
    assert gate.allows("apr-1", now=now) is False


def test_proceeds_before_expiry_and_stops_at_expiry() -> None:
    gate = InMemoryHitlGate()
    expires_at = _at(13)
    opened = _at(12)
    gate.request(approval_id="apr-2", action="approve.payment", subject="INV-1042", expires_at=expires_at)
    gate.decide("apr-2", approved=True, now=opened)
    assert_proceeds_with_approval(gate, "apr-2", now=opened)
    one_second_before = expires_at - timedelta(seconds=1)
    assert gate.allows("apr-2", now=one_second_before) is True
    assert_approval_expired(gate, "apr-2", now=expires_at)


def test_late_decision_does_not_approve() -> None:
    gate = InMemoryHitlGate()
    expires_at = _at(13)
    gate.request(approval_id="apr-3", action="approve.payment", subject="INV-1042", expires_at=expires_at)
    recorded = gate.decide("apr-3", approved=True, now=expires_at)
    assert recorded.status is ApprovalStatus.EXPIRED
    with pytest.raises(AssertionError):
        assert_proceeds_with_approval(gate, "apr-3", now=expires_at)

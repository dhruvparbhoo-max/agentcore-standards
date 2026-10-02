"""A token is single-use, actor-bound, and expired tokens do not proceed."""

from datetime import UTC, datetime, timedelta

import pytest
from agentcore_approvals import ApprovalError, ApprovalGate

_NOW = datetime(2026, 10, 2, tzinfo=UTC)


def test_consume_requires_a_different_approver_and_spends_the_token() -> None:
    gate = ApprovalGate()
    token_id = gate.issue(
        tool_name="escalate_ticket",
        args_hash="a" * 64,
        actor_id="actor-1",
        ttl_seconds=60,
        now=_NOW,
    )
    with pytest.raises(ApprovalError) as pending:
        gate.consume(
            token_id,
            tool_name="escalate_ticket",
            args_hash="a" * 64,
            actor_id="actor-1",
            now=_NOW,
        )
    assert pending.value.code == "not_approved"
    with pytest.raises(ApprovalError) as same:
        gate.decide(token_id, approved=True, approver_id="actor-1", now=_NOW)
    assert same.value.code == "approver_is_actor"
    gate.decide(token_id, approved=True, approver_id="reviewer-1", now=_NOW)
    gate.consume(
        token_id,
        tool_name="escalate_ticket",
        args_hash="a" * 64,
        actor_id="actor-1",
        now=_NOW,
    )
    with pytest.raises(ApprovalError) as reused:
        gate.consume(
            token_id,
            tool_name="escalate_ticket",
            args_hash="a" * 64,
            actor_id="actor-1",
            now=_NOW,
        )
    assert reused.value.code == "consumed"
    actions = [item.action for item in gate.audit()]
    assert actions == ["issue", "reject-self", "approved", "consume"]


def test_expired_and_mismatched_tokens_do_not_proceed() -> None:
    gate = ApprovalGate()
    token_id = gate.issue(
        tool_name="apply_step",
        args_hash="b" * 64,
        actor_id="actor-1",
        ttl_seconds=30,
        now=_NOW,
    )
    gate.decide(token_id, approved=True, approver_id="reviewer-1", now=_NOW)
    with pytest.raises(ApprovalError) as mismatch:
        gate.consume(
            token_id,
            tool_name="apply_step",
            args_hash="c" * 64,
            actor_id="actor-1",
            now=_NOW,
        )
    assert mismatch.value.code == "mismatch"
    later = _NOW + timedelta(seconds=30)
    with pytest.raises(ApprovalError) as expired:
        gate.consume(
            token_id,
            tool_name="apply_step",
            args_hash="b" * 64,
            actor_id="actor-1",
            now=later,
        )
    assert expired.value.code == "expired"

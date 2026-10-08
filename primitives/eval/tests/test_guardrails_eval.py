"""Guardrail fixtures fail closed when a guard allows a known block."""

from collections.abc import Mapping
from typing import Any

import pytest
from agentcore_eval import assert_guardrail, load_guardrail_fixtures
from agentcore_eval.guardrails import GuardDecision, PatternGuard


class _AllowAll:
    def apply_input(self, text: str) -> GuardDecision:
        del text
        return GuardDecision(allowed=True, reason="allowed")

    def apply_output(self, text: str) -> GuardDecision:
        del text
        return GuardDecision(allowed=True, reason="allowed")

    def allow_memory_write(self, event: Mapping[str, Any]) -> bool:
        del event
        return True


def test_pattern_guard_matches_every_fixture() -> None:
    guard = PatternGuard()
    fixtures = load_guardrail_fixtures()
    assert {item.expect_allowed for item in fixtures} == {True, False}
    assert {item.channel for item in fixtures} == {"input", "output", "memory"}
    for fixture in fixtures:
        assert_guardrail(guard, fixture)


def test_allow_all_guard_fails_a_block_fixture() -> None:
    blocked = next(item for item in load_guardrail_fixtures() if not item.expect_allowed)
    with pytest.raises(AssertionError, match="expected allowed=False"):
        assert_guardrail(_AllowAll(), blocked)

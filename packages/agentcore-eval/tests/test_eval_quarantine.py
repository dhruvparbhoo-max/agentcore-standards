"""Offline stand-ins stay importable from their modules, not the package root."""

import pytest


def test_package_root_refuses_eval_stand_ins() -> None:
    with pytest.raises(ImportError, match="offline eval stand-in"):
        from agentcore_eval import PatternGuard  # noqa: F401

    from agentcore_eval.guardrails import PatternGuard as Guard

    assert Guard is not None

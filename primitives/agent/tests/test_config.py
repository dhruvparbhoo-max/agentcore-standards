from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from agentcore_agent import PatternError, load_pattern, validate_pattern
from agentcore_agent.config import ACTOR_HEADER


def test_template_is_valid(template_raw: dict[str, Any]) -> None:
    assert validate_pattern(template_raw, folder_name="_template") == []


def test_every_problem_is_reported_at_once(template_raw: dict[str, Any]) -> None:
    raw = {**template_raw, "framework": "crewai", "deployment": "zip"}
    del raw["memory"]
    problems = validate_pattern(raw)
    assert len(problems) == 3
    assert any("memory" in problem for problem in problems)


@pytest.mark.parametrize(
    ("override", "fragment"),
    [
        ({"lifecycle": {"idle_timeout_s": 900}}, "chat patterns use idle_timeout_s 300"),
        ({"risk_tier": "high"}, "approval.reviewers"),
        ({"memory": {"enabled": True, "write_policy": "off"}}, "memory.write_policy"),
        ({"knowledge": {"enabled": True}}, "knowledge.gateway_target"),
        ({"model": {"fallback": "eu.anthropic.claude-sonnet-4-5-20250929-v1:0"}}, "model.fallback"),
        ({"data": {"audit_retention_days": 30}}, "data.audit_retention_days"),
        ({"context": {"compaction_at": 64000}}, "context.compaction_at"),
        ({"runtime": {"session_header": "Mcp-Session-Id"}}, "runtime.session_header"),
        ({"runtime": {"header_allowlist": ["X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"]}}, "reserved"),
        ({"runtime": {"header_allowlist": ["Authorization"]}}, ACTOR_HEADER),
        ({"cost": {"max_usd_per_run": 100}}, "cost.max_usd_per_run"),
        ({"trigger": "event", "approval": {"required_for": ["send"]}}, "lifecycle.resumable"),
    ],
)
def test_cross_field_rules(make_pattern: Callable[..., Path], override: dict[str, Any], fragment: str) -> None:
    folder = make_pattern(**override)
    with pytest.raises(PatternError) as caught:
        load_pattern(folder)
    assert any(fragment in problem for problem in caught.value.problems), caught.value.problems


def test_name_must_match_folder(make_pattern: Callable[..., Path], tmp_path: Path) -> None:
    folder = make_pattern("right-name")
    renamed = folder.rename(tmp_path / "other-name")
    with pytest.raises(PatternError, match="folder name"):
        load_pattern(renamed)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PatternError, match="missing"):
        load_pattern(tmp_path)


def test_approval_expiry_cannot_exceed_the_gate(template_raw: dict[str, Any]) -> None:
    raw = {**template_raw, "approval": {**template_raw["approval"], "expire_s": 90000}}
    assert any("expire_s" in problem for problem in validate_pattern(raw))

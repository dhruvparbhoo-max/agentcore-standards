from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import yaml
from agentcore_agent import load_pattern
from agentcore_agent.agentcore_json import write_generated
from agentcore_agent.checks import check_kit
from agentcore_agent.cli import main
from agentcore_agent.environment import load_environment
from agentcore_agent.production import production_problems

REPO = Path(__file__).resolve().parents[3]


def _ready(folder: Path) -> Path:
    write_generated(load_pattern(folder))
    return folder


def _items(folder: Path, repo_root: Path = REPO) -> set[int]:
    return {problem.item for problem in check_kit(folder, repo_root=repo_root)}


def test_copied_template_passes(make_pattern: Callable[..., Path]) -> None:
    assert check_kit(_ready(make_pattern()), repo_root=REPO) == []


def test_missing_eval_set_fails(make_pattern: Callable[..., Path]) -> None:
    folder = _ready(make_pattern())
    (folder / "eval" / "golden_set.json").unlink()
    assert 8 in _items(folder)


def test_missing_tracing_fails(make_pattern: Callable[..., Path]) -> None:
    folder = _ready(make_pattern())
    shutil.rmtree(folder / "agent")
    assert {6, 10, 12} <= _items(folder)


def test_agent_that_skips_build_agent_fails(make_pattern: Callable[..., Path]) -> None:
    folder = _ready(make_pattern())
    (folder / "agent" / "template_agent" / "app.py").write_text("def invoke(payload):\n    return payload\n")
    assert 10 in _items(folder)


def test_tool_without_cedar_permit_fails(make_pattern: Callable[..., Path], tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path, action="read")
    folder = _ready(make_pattern(tools={"from_registry": ["lookup_order"]}))
    problems = [str(p) for p in check_kit(folder, repo_root=repo)]
    assert any("no Cedar permit" in problem for problem in problems)


def test_cedar_wildcard_fails(make_pattern: Callable[..., Path]) -> None:
    folder = _ready(make_pattern())
    (folder / "policies" / "tools.cedar").write_text("permit(\n  principal,\n  action,\n  resource\n);\n")
    assert any("every action" in str(p) for p in check_kit(folder, repo_root=REPO))


def test_risky_tool_without_approval_fails(make_pattern: Callable[..., Path], tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path, action="send")
    folder = _ready(make_pattern(tools={"from_registry": ["lookup_order"]}))
    _permit(folder, "lookup_order")
    problems = [str(p) for p in check_kit(folder, repo_root=repo)]
    assert "item 5: tool lookup_order does send; approval.required_for must list send" in problems


def test_risky_tool_with_approval_passes(make_pattern: Callable[..., Path], tmp_path: Path) -> None:
    repo = _fake_repo(tmp_path, action="send")
    folder = _ready(make_pattern(tools={"from_registry": ["lookup_order"]}, approval={"required_for": ["send"]}))
    _permit(folder, "lookup_order")
    assert check_kit(folder, repo_root=repo) == []


def test_stamped_release_id_in_git_fails(make_pattern: Callable[..., Path]) -> None:
    folder = _ready(make_pattern(release={"id": "rel-abc"}))
    assert 2 in _items(folder)


def test_retrieval_pattern_needs_source_backed_cases(make_pattern: Callable[..., Path]) -> None:
    folder = make_pattern(
        knowledge={"enabled": True, "gateway_target": "knowledge-base", "filter_from": "verified-login"},
        eval={"golden_set": "eval/golden_set.json", "threshold": 0.8, "groundedness": 0.7, "runs_per_case": 1},
    )
    _ready(folder)
    assert any("source-backed" in str(p) for p in check_kit(folder, repo_root=REPO))


def test_production_mode_refuses_missing_controls(make_pattern: Callable[..., Path]) -> None:
    folder = _ready(make_pattern())
    problems = production_problems(load_pattern(folder), load_environment("prod", repo_root=REPO), repo_root=REPO)
    for control in ("front_door", "guardrails_service", "audit_store", "kill_switch", "quotas"):
        assert f"controls.{control}: must be on in production" in problems


def test_production_mode_passes_when_every_control_is_on(make_pattern: Callable[..., Path], tmp_path: Path) -> None:
    folder = _ready(make_pattern())
    repo = tmp_path / "repo"
    (repo / "config" / "environments").mkdir(parents=True)
    raw = yaml.safe_load((REPO / "config" / "environments" / "prod.yaml").read_text(encoding="utf-8"))
    raw["controls"] = dict.fromkeys(raw["controls"], True)
    (repo / "config" / "environments" / "prod.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert production_problems(load_pattern(folder), load_environment("prod", repo_root=repo), repo_root=repo) == []


def test_cli_check_kit_and_production(make_pattern: Callable[..., Path]) -> None:
    folder = _ready(make_pattern())
    lines: list[str] = []
    assert main(["--repo-root", str(REPO), "check-kit", str(folder)], echo=lines.append) == 0
    assert main(["--repo-root", str(REPO), "production-check", str(folder), "--env", "prod"], echo=lines.append) == 1
    assert any(line.startswith("REFUSE controls.front_door") for line in lines)
    assert main(["--repo-root", str(REPO), "generate", "--check", str(folder)], echo=lines.append) == 0


def _fake_repo(tmp_path: Path, *, action: str) -> Path:
    repo = tmp_path / "repo"
    tool = repo / "primitives" / "gateway-tools" / "lookup_order"
    tool.mkdir(parents=True)
    (tool / "tool.yaml").write_text(yaml.safe_dump({"name": "lookup_order", "action": action}), encoding="utf-8")
    shutil.copytree(REPO / "docs" / "runbooks", repo / "docs" / "runbooks")
    return repo


def _permit(folder: Path, tool: str) -> None:
    (folder / "policies" / "tools.cedar").write_text(
        f'permit(\n  principal,\n  action == AgentCore::Action::"orders___{tool}",\n'
        '  resource == AgentCore::Gateway::"{{GATEWAY_ARN}}"\n);\n'
    )


def test_missing_runbook_fails(make_pattern: Callable[..., Path]) -> None:
    folder = _ready(make_pattern(runbook_url="docs/runbooks/missing.md"))
    problems = check_kit(folder, repo_root=REPO)
    assert [str(problem) for problem in problems if problem.item == 12] == [
        "item 12: runbook_url docs/runbooks/missing.md does not exist in the repo"
    ]

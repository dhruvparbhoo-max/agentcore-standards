"""Contract tests: the kit is complete, generated files are current, and the CLI accepts them."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from agentcore_agent import load_pattern
from agentcore_agent.agentcore_json import render_agentcore_json, stale_generated
from agentcore_agent.checks import check_kit
from agentcore_agent.config import ACTOR_HEADER
from agentcore_agent.environment import load_environment
from agentcore_agent.production import production_problems
from bedrock_agentcore.runtime.context import RequestContext
from jsonschema import Draft202012Validator

PATTERN = Path(__file__).resolve().parents[1]
REPO = PATTERN.parents[1]


def test_kit_is_complete() -> None:
    assert check_kit(PATTERN, repo_root=REPO) == []


def test_generated_files_are_current() -> None:
    assert stale_generated(load_pattern(PATTERN)) == []


def test_runtime_config_keeps_the_controls() -> None:
    runtime = render_agentcore_json(load_pattern(PATTERN))["runtimes"][0]
    assert runtime["build"] == "Container"
    assert ACTOR_HEADER in runtime["requestHeaderAllowlist"]
    assert runtime["lifecycleConfiguration"] == {"idleRuntimeSessionTimeout": 300, "maxLifetime": 1800}
    assert runtime["instrumentation"] == {"enableOtel": True}


def test_answer_matches_its_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTCORE_MODEL", "scripted")
    from template_agent import app

    monkeypatch.setattr(app, "_agent", None)
    context = RequestContext(session_id="s" * 40, request_headers={ACTOR_HEADER: "actor-1"}, request=None)
    body: dict[str, Any] = app.invoke({"prompt": "hello"}, context)
    schema = json.loads((PATTERN / "schemas" / "answer.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(body)) == []


def test_production_gate_refuses_until_platform_controls_exist() -> None:
    problems = production_problems(load_pattern(PATTERN), load_environment("prod", repo_root=REPO), repo_root=REPO)
    assert "controls.front_door: must be on in production" in problems


def test_development_gate_passes() -> None:
    assert production_problems(load_pattern(PATTERN), load_environment("dev", repo_root=REPO), repo_root=REPO) == []


def test_infra_synthesises() -> None:
    import aws_cdk as cdk
    from aws_cdk import assertions

    spec_path = PATTERN / "infra" / "app.py"
    namespace: dict[str, Any] = {"__name__": "template_infra", "__file__": str(spec_path)}
    exec(compile(spec_path.read_text(encoding="utf-8"), str(spec_path), "exec"), namespace)
    stack = namespace["build"](cdk.App(), "dev")
    template = assertions.Template.from_stack(stack)
    template.resource_count_is("AWS::ECR::Repository", 1)
    template.has_resource_properties("AWS::Logs::LogGroup", {"RetentionInDays": 90})


@pytest.mark.skipif(shutil.which("agentcore") is None, reason="AgentCore CLI (@aws/agentcore) is not installed")
def test_agentcore_cli_accepts_the_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(PATTERN / "agentcore", project / "agentcore")
    result = subprocess.run(
        ["agentcore", "validate", "-d", str(project)], capture_output=True, text=True, check=False, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr

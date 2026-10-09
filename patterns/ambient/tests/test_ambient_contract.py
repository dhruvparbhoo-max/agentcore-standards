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
    assert runtime["lifecycleConfiguration"] == {"idleRuntimeSessionTimeout": 1800, "maxLifetime": 14400}
    assert runtime["instrumentation"] == {"enableOtel": True}


def test_answer_matches_its_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTCORE_MODEL", "scripted")
    from ambient import app

    monkeypatch.setattr(app, "_agent", None)
    context = RequestContext(session_id="s" * 40, request_headers={ACTOR_HEADER: "ambient-worker"}, request=None)
    body: dict[str, Any] = app.invoke({"prompt": "index the new invoice pack"}, context)
    schema = json.loads((PATTERN / "schemas" / "answer.json").read_text(encoding="utf-8"))
    assert list(Draft202012Validator(schema).iter_errors(body)) == []


def test_production_gate_refuses_until_platform_controls_exist() -> None:
    problems = production_problems(load_pattern(PATTERN), load_environment("prod", repo_root=REPO), repo_root=REPO)
    assert "controls.front_door: must be on in production" not in problems
    assert "controls.guardrails_service: must be on in production" in problems


def test_development_gate_passes() -> None:
    assert production_problems(load_pattern(PATTERN), load_environment("dev", repo_root=REPO), repo_root=REPO) == []


def _infra() -> dict[str, Any]:
    spec_path = PATTERN / "infra" / "app.py"
    namespace: dict[str, Any] = {"__name__": "template_infra", "__file__": str(spec_path)}
    exec(compile(spec_path.read_text(encoding="utf-8"), str(spec_path), "exec"), namespace)
    return namespace


def test_infra_synthesises() -> None:
    import aws_cdk as cdk
    from aws_cdk import assertions

    app = cdk.App()
    stack = _infra()["build"](app, "dev")
    template = assertions.Template.from_stack(stack)
    template.resource_count_is("AWS::ECR::Repository", 1)
    template.has_resource_properties("AWS::Logs::LogGroup", {"RetentionInDays": 90})
    template.resource_count_is("AWS::Bedrock::ApplicationInferenceProfile", 2)
    template.resource_count_is("AWS::EC2::VPC", 0)
    names = [child.node.id for child in app.node.children]
    assert stack.node.id in names
    assert f"{stack.node.id}-edge" not in names


def test_prod_infra_has_the_network_and_the_edge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import aws_cdk as cdk
    from agentcore_agent.hardening import front_door_policy
    from aws_cdk import assertions

    arn = "arn:" + "aws:bedrock-agentcore:eu-west-2:000000000000:runtime/template-abc"
    policy = tmp_path / "policy.json"
    document = front_door_policy(load_pattern(PATTERN), load_environment("prod", repo_root=REPO), runtime_arn=arn)
    policy.write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setenv("FRONT_DOOR_ISSUER", "https://issuer.example.invalid")
    monkeypatch.setenv("FRONT_DOOR_AUDIENCE", "client")
    images: list[str] = []

    def no_build(base_image: str = "") -> Any:
        images.append(base_image)

        def image(scope: Any, handler: str) -> Any:
            name = handler.split(".")[-2]
            repository = cdk.aws_ecr.Repository.from_repository_name(scope, f"Repo{name}", "front-door")
            return cdk.aws_lambda.DockerImageCode.from_ecr(repository, cmd=[handler])

        return image

    namespace = _infra()
    namespace["image_asset"] = no_build
    with pytest.raises(ValueError, match="front_door_policy"):
        namespace["build"](cdk.App(), "prod", runtime_arn=arn)
    app = cdk.App()
    stack = namespace["build"](app, "prod", runtime_arn=arn, front_door_policy=str(policy))
    foundation = assertions.Template.from_stack(stack)
    foundation.resource_count_is("AWS::EC2::VPC", 1)
    foundation.resource_count_is("AWS::Route53Resolver::FirewallRuleGroupAssociation", 1)
    edge = assertions.Template.from_stack(app.node.find_child(f"{stack.node.id}-edge"))
    edge.resource_count_is("AWS::DynamoDB::GlobalTable", 2)
    edge.resource_count_is("AWS::ApiGatewayV2::Api", 1)
    alarms = edge.find_resources("AWS::CloudWatch::Alarm")
    assert all("Check first" in json.dumps(body) for body in alarms.values())
    assert len(alarms) == 8
    assert images == [""]


@pytest.mark.skipif(shutil.which("agentcore") is None, reason="AgentCore CLI (@aws/agentcore) is not installed")
def test_agentcore_cli_accepts_the_project(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(PATTERN / "agentcore", project / "agentcore")
    result = subprocess.run(
        ["agentcore", "validate", "-d", str(project)], capture_output=True, text=True, check=False, timeout=120
    )
    assert result.returncode == 0, result.stdout + result.stderr

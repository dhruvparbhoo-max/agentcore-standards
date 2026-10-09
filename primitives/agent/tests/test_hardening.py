from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import agentcore_front_door
import pytest
from agentcore_agent import load_pattern
from agentcore_agent.cli import main
from agentcore_agent.config import ACTOR_HEADER, OBO_HEADER, PatternError
from agentcore_agent.environment import load_environment
from agentcore_agent.hardening import front_door_policy, harden, harden_request, hardening_problems, invoke_policy
from agentcore_front_door import AgentPolicy

REPO = Path(__file__).resolve().parents[3]
RUNTIME_ARN = "arn:" + "aws:bedrock-agentcore:eu-west-2:000000000000:runtime/demo-abc"
DOOR_ROLE = "arn:" + "aws:iam::000000000000:role/front-door"

DEPLOYED: dict[str, Any] = {
    "agentRuntimeId": "demo-abc",
    "roleArn": "role",
    "agentRuntimeArtifact": {"containerConfiguration": {"containerUri": "repo@sha256:abc"}},
    "networkConfiguration": {"networkMode": "VPC", "networkModeConfig": {"subnets": ["s"], "securityGroups": ["g"]}},
    "requestHeaderConfiguration": {"requestHeaderAllowlist": [ACTOR_HEADER]},
    "lifecycleConfiguration": {"idleRuntimeSessionTimeout": 300, "maxLifetime": 1800},
    "protocolConfiguration": {"serverProtocol": "HTTP"},
    "environmentVariables": {"AGENTCORE_PATTERN": "demo"},
    "status": "READY",
}


class Control:
    def __init__(self, runtime: Mapping[str, Any], policy: str = "") -> None:
        self.runtime = dict(runtime)
        self.policy = policy
        self.updates: list[dict[str, Any]] = []

    def get_agent_runtime(self, **kwargs: Any) -> Mapping[str, Any]:
        return self.runtime

    def update_agent_runtime(self, **kwargs: Any) -> Mapping[str, Any]:
        self.updates.append(kwargs)
        self.runtime.update(kwargs)
        return {}

    def put_resource_policy(self, **kwargs: Any) -> Mapping[str, Any]:
        self.policy = kwargs["policy"]
        return {}

    def get_resource_policy(self, **kwargs: Any) -> Mapping[str, Any]:
        return {"policy": self.policy}


def test_headers_match_the_front_door() -> None:
    assert agentcore_front_door.ACTOR_HEADER == ACTOR_HEADER
    assert agentcore_front_door.OBO_HEADER == OBO_HEADER


def test_policy_renders_from_the_pattern_and_loads_in_the_front_door() -> None:
    config = load_pattern(REPO / "patterns" / "_template")
    environment = load_environment("dev", repo_root=REPO)
    document = front_door_policy(config, environment, runtime_arn=RUNTIME_ARN, release_id="rel-9")
    policy = AgentPolicy.from_mapping(document)
    assert policy.agent == "_template" and policy.endpoint == "DEV" and policy.release_id == "rel-9"
    assert policy.max_turns == int(config.section("lifecycle")["max_turns"])
    assert policy.obo == ()


def test_user_scopes_become_obo_targets_and_need_the_header(make_pattern: Callable[..., Path]) -> None:
    with pytest.raises(PatternError, match="Obo-Tokens"):
        load_pattern(make_pattern(identity={"acts_as": "user", "scopes": {"hr-api": ["hr.read"]}}))
    folder = make_pattern(
        "obo-pattern",
        identity={"acts_as": "user", "scopes": {"hr-api": ["hr.read"]}},
        runtime={"header_allowlist": ["Authorization", ACTOR_HEADER, OBO_HEADER]},
    )
    document = front_door_policy(load_pattern(folder), load_environment("dev", repo_root=REPO))
    assert document["obo"] == [{"provider": "hr-api", "scopes": ["hr.read"]}]


def test_harden_copies_every_deployed_field_and_requires_mmds() -> None:
    request = harden_request(DEPLOYED, runtime_id="demo-abc")
    for name in ("roleArn", "agentRuntimeArtifact", "networkConfiguration", "requestHeaderConfiguration"):
        assert request[name] == DEPLOYED[name]
    assert request["metadataConfiguration"] == {"requireMMDSV2": True}
    assert "status" not in request


def test_harden_refuses_a_partial_update() -> None:
    with pytest.raises(ValueError, match="roleArn"):
        harden_request({"agentRuntimeArtifact": {}}, runtime_id="x")


def test_harden_is_idempotent() -> None:
    control = Control(DEPLOYED)
    assert harden(control, runtime_id="demo-abc") is True
    assert harden(control, runtime_id="demo-abc") is False
    assert len(control.updates) == 1


def test_invoke_policy_denies_everyone_but_the_front_door() -> None:
    statement = invoke_policy(RUNTIME_ARN, allowed_principals=[DOOR_ROLE])["Statement"][0]
    assert statement["Effect"] == "Deny" and statement["Principal"] == "*"
    assert "bedrock-agentcore:InvokeAgentRuntime" in statement["Action"]
    assert statement["Condition"]["ArnNotEquals"]["aws:PrincipalArn"] == [DOOR_ROLE]


def test_hardening_problems_until_both_are_applied() -> None:
    control = Control(DEPLOYED)
    problems = hardening_problems(control, runtime_id="demo-abc", runtime_arn=RUNTIME_ARN, front_door_role=DOOR_ROLE)
    assert len(problems) == 2
    harden(control, runtime_id="demo-abc")
    control.policy = json.dumps(invoke_policy(RUNTIME_ARN, allowed_principals=[DOOR_ROLE]))
    assert hardening_problems(control, runtime_id="demo-abc", runtime_arn=RUNTIME_ARN, front_door_role=DOOR_ROLE) == []


def test_cli_writes_the_policy(tmp_path: Path) -> None:
    out = tmp_path / "policy.json"
    lines: list[str] = []
    code = main(
        [
            "--repo-root",
            str(REPO),
            "front-door-policy",
            str(REPO / "patterns" / "_template"),
            "--env",
            "dev",
            "--output",
            str(out),
        ],
        echo=lines.append,
    )
    assert code == 0 and json.loads(out.read_text())["agent"] == "_template"

"""Settings the AgentCore CLI project file cannot express, applied after ``agentcore deploy``.

- ``front_door_policy`` renders the ``AgentPolicy`` the front door enforces for
  this pattern (``agentcore_front_door.policy``). Runtime ids arrive at deploy
  time; the rendered file lives under ``build/``, outside git.
- ``harden`` sets ``metadataConfiguration.requireMMDSV2`` on the runtime (the
  MicroVM metadata service answers only session-token requests, the IMDSv2
  rule from docs/design/library.md "Code the model wrote"). ``UpdateAgentRuntime``
  replaces the whole config, so every field ``GetAgentRuntime`` returned is
  copied into the update; leaving the header allowlist out would drop headers.
- ``invoke_policy`` is the runtime resource policy: deny ``InvokeAgentRuntime``
  to every principal except the front door role (and, until the Runtime judge
  calls through the front door, the judge role named explicitly).

The CLI schema has no field for either setting, so these are boto3 calls on
``bedrock-agentcore-control``. No AgentCore reference repo sets them; the
fields are from the service API (botocore ``UpdateAgentRuntime`` and
``PutResourcePolicy``).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from agentcore_agent.config import PatternConfig
from agentcore_agent.environment import EnvironmentConfig

INVOKE_ACTIONS = ("bedrock-agentcore:InvokeAgentRuntime", "bedrock-agentcore:InvokeAgentRuntimeForUser")
_COPIED = (
    "roleArn",
    "agentRuntimeArtifact",
    "networkConfiguration",
    "description",
    "authorizerConfiguration",
    "requestHeaderConfiguration",
    "protocolConfiguration",
    "lifecycleConfiguration",
    "environmentVariables",
    "filesystemConfigurations",
    "capacityProviderConfiguration",
    "platformVersion",
)


class HardeningClient(Protocol):
    def get_agent_runtime(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def update_agent_runtime(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def put_resource_policy(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_resource_policy(self, **kwargs: Any) -> Mapping[str, Any]: ...


def front_door_policy(
    config: PatternConfig,
    environment: EnvironmentConfig,
    *,
    runtime_arn: str = "",
    workload_name: str = "",
    release_id: str = "",
    model_aliases: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    lifecycle = config.section("lifecycle")
    cost = config.section("cost")
    identity = config.section("identity")
    acts_as = str(identity["acts_as"])
    scopes: Mapping[str, Sequence[str]] = identity.get("scopes") or {}
    obo = (
        [{"provider": name, "scopes": list(values)} for name, values in sorted(scopes.items())]
        if acts_as == "user"
        else []
    )
    return {
        "agent": config.name,
        "team": str(config.section("model")["team_tag"]),
        "acts_as": acts_as,
        "endpoint": environment.endpoint,
        "release_id": release_id or config.release_id,
        "tools": list(config.tools),
        "max_turns": int(lifecycle["max_turns"]),
        "max_steps": int(lifecycle["max_steps"]),
        "timeout_s": int(lifecycle["timeout_s"]),
        "session_id_min": int(lifecycle["session_id_min"]),
        "max_usd_per_run": float(cost["max_usd_per_run"]),
        "monthly_cap_usd": float(cost["monthly_cap_usd"]),
        "on_cap": str(cost["on_cap"]),
        "runtime_arn": runtime_arn,
        "workload_name": workload_name,
        "obo": obo,
        "model_aliases": dict(model_aliases or {}),
    }


def harden_request(runtime: Mapping[str, Any], *, runtime_id: str) -> dict[str, Any]:
    """The full ``UpdateAgentRuntime`` input: everything deployed, plus MMDSv2 required."""
    request: dict[str, Any] = {"agentRuntimeId": runtime_id}
    for name in _COPIED:
        value = runtime.get(name)
        if value not in (None, "", {}, []):
            request[name] = value
    missing = [name for name in ("roleArn", "agentRuntimeArtifact") if name not in request]
    if missing:
        raise ValueError(f"GetAgentRuntime returned no {', '.join(missing)}; refusing a partial update")
    request["metadataConfiguration"] = {"requireMMDSV2": True}
    return request


def harden(client: HardeningClient, *, runtime_id: str) -> bool:
    """Require MMDSv2. False when it was already required (no update made)."""
    runtime = client.get_agent_runtime(agentRuntimeId=runtime_id)
    if runtime.get("metadataConfiguration", {}).get("requireMMDSV2") is True:
        return False
    client.update_agent_runtime(**harden_request(runtime, runtime_id=runtime_id))
    return True


def invoke_policy(runtime_arn: str, *, allowed_principals: Sequence[str]) -> dict[str, Any]:
    if not allowed_principals:
        raise ValueError("name at least the front door role")
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "OnlyTheFrontDoorStartsSessions",
                "Effect": "Deny",
                "Principal": "*",
                "Action": list(INVOKE_ACTIONS),
                "Resource": [runtime_arn, f"{runtime_arn}/*"],
                "Condition": {"ArnNotEquals": {"aws:PrincipalArn": sorted(allowed_principals)}},
            }
        ],
    }


def put_invoke_policy(client: HardeningClient, runtime_arn: str, *, allowed_principals: Sequence[str]) -> None:
    policy = invoke_policy(runtime_arn, allowed_principals=allowed_principals)
    client.put_resource_policy(resourceArn=runtime_arn, policy=json.dumps(policy, sort_keys=True))


def hardening_problems(
    client: HardeningClient, *, runtime_id: str, runtime_arn: str, front_door_role: str
) -> list[str]:
    """What ``verify`` adds in production: MMDSv2 on, and the front door is the only caller."""
    problems: list[str] = []
    runtime = client.get_agent_runtime(agentRuntimeId=runtime_id)
    if runtime.get("metadataConfiguration", {}).get("requireMMDSV2") is not True:
        problems.append("metadataConfiguration.requireMMDSV2: true (run `agentcore-kit harden`)")
    try:
        raw = client.get_resource_policy(resourceArn=runtime_arn).get("policy", "")
        document = json.loads(raw) if raw else {}
    except Exception as exc:
        problems.append(f"resource policy: unreadable ({type(exc).__name__})")
        return problems
    denies = [
        statement
        for statement in document.get("Statement", [])
        if statement.get("Effect") == "Deny" and "bedrock-agentcore:InvokeAgentRuntime" in statement.get("Action", [])
    ]
    allowed = {
        principal
        for statement in denies
        for principal in statement.get("Condition", {}).get("ArnNotEquals", {}).get("aws:PrincipalArn", [])
    }
    if not denies or front_door_role not in allowed:
        problems.append("resource policy: InvokeAgentRuntime must be denied to everyone but the front door role")
    return problems

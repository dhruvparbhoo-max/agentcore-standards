"""After a deploy: re-read the runtime from AgentCore and compare it with what ``pattern.yaml`` promised.

An update replaces the whole runtime config, so a dropped header allowlist or
lifecycle setting shows up here rather than as silent missing headers. The
golden set runs separately through the Runtime judge; ``verify`` does not
replace it. This calls ``bedrock-agentcore-control`` and needs AWS credentials.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from agentcore_agent.config import PatternConfig

READY = "READY"


class ControlClient(Protocol):
    def get_agent_runtime(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_agent_runtime_endpoint(self, **kwargs: Any) -> Mapping[str, Any]: ...


def verify_runtime(
    config: PatternConfig,
    client: ControlClient,
    *,
    runtime_id: str,
    release_id: str,
    endpoint: str,
) -> list[str]:
    """Every difference between the deployed runtime and the pattern. Empty means verified."""
    problems: list[str] = []

    def require(condition: bool, field: str, expectation: str) -> None:
        if not condition:
            problems.append(f"{field}: {expectation}")

    runtime = client.get_agent_runtime(agentRuntimeId=runtime_id)
    require(runtime.get("status") == READY, "status", f"{READY}, got {runtime.get('status')}")

    wanted_headers = sorted(config.section("runtime")["header_allowlist"])
    got_headers = sorted(runtime.get("requestHeaderConfiguration", {}).get("requestHeaderAllowlist", []))
    require(got_headers == wanted_headers, "requestHeaderAllowlist", f"{wanted_headers}, got {got_headers}")

    lifecycle = config.section("lifecycle")
    got_lifecycle = runtime.get("lifecycleConfiguration", {})
    require(
        got_lifecycle.get("idleRuntimeSessionTimeout") == lifecycle["idle_timeout_s"]
        and got_lifecycle.get("maxLifetime") == lifecycle["max_lifetime_s"],
        "lifecycleConfiguration",
        f"idle {lifecycle['idle_timeout_s']} and max {lifecycle['max_lifetime_s']}, got {dict(got_lifecycle)}",
    )

    protocol = config.section("runtime").get("protocol", "HTTP")
    got_protocol = runtime.get("protocolConfiguration", {}).get("serverProtocol", "HTTP")
    require(got_protocol == protocol, "protocol", f"{protocol}, got {got_protocol}")

    variables = runtime.get("environmentVariables", {})
    require(variables.get("AGENTCORE_RELEASE_ID") == release_id, "AGENTCORE_RELEASE_ID", release_id)
    require(variables.get("AGENTCORE_PATTERN") == config.name, "AGENTCORE_PATTERN", config.name)

    artifact = runtime.get("agentRuntimeArtifact", {}).get("containerConfiguration", {})
    require("@sha256:" in str(artifact.get("containerUri", "")), "containerUri", "pinned by digest")

    deployed = client.get_agent_runtime_endpoint(agentRuntimeId=runtime_id, endpointName=endpoint)
    require(deployed.get("status") == READY, f"endpoint {endpoint}", f"{READY}, got {deployed.get('status')}")
    require(
        str(deployed.get("liveVersion")) == str(runtime.get("agentRuntimeVersion")),
        f"endpoint {endpoint}",
        f"serving version {runtime.get('agentRuntimeVersion')}, got {deployed.get('liveVersion')}",
    )
    return problems

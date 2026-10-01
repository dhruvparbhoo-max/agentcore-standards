"""Gateway binding. The default target is Lambda. MCP servers are a later path."""

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from agentcore_tools.errors import ToolConfigurationError
from agentcore_tools.naming import (
    gateway_tool_name,
    require_resource_id,
    require_server_name,
    require_target_name,
    require_tool_name,
)
from agentcore_tools.policy import Policy


class LambdaTarget:
    """One Gateway Lambda target and the logical tools it fronts."""

    def __init__(self, *, name: str, tool_names: tuple[str, ...]) -> None:
        self.name = require_target_name(name)
        self.tool_names = tuple(require_tool_name(tool) for tool in tool_names)

    def visible_name(self, tool_name: str) -> str:
        """Return ``{target}___{tool}`` for a tool on this target."""
        if tool_name not in self.tool_names:
            raise ToolConfigurationError("tool is not on this Lambda target")
        return gateway_tool_name(self.name, tool_name)


class McpServerTarget:
    """Placeholder for a Gateway MCP server target.

    The default demo path is Lambda. Calling ``to_configuration`` fails so a
    caller cannot accidentally sync an unfinished MCP target.
    """

    def __init__(self, *, name: str, server_name: str) -> None:
        self.name = require_target_name(name)
        self.server_name = require_server_name(server_name)

    def to_configuration(self) -> Mapping[str, Any]:
        raise ToolConfigurationError("MCP server targets are not implemented; use a Lambda target")


class GatewayBinding:
    """A gateway id, its live policy, and the Lambda targets registered with it."""

    def __init__(
        self,
        *,
        gateway_id: str,
        policy: Policy,
        targets: tuple[LambdaTarget, ...],
    ) -> None:
        self.gateway_id = require_resource_id(gateway_id)
        self.policy = policy
        self.targets = targets

    def target(self, name: str) -> LambdaTarget:
        """Return the Lambda target named ``name``."""
        for item in self.targets:
            if item.name == name:
                return item
        raise ToolConfigurationError("unknown Lambda target")

    def target_for_tool(self, tool_name: str) -> LambdaTarget | None:
        """Return the Lambda target that publishes ``tool_name``, if any."""
        for item in self.targets:
            if tool_name in item.tool_names:
                return item
        return None


def build_lambda_target_request(
    *,
    gateway_id: str,
    target_name: str,
    lambda_arn: str,
    definitions: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the ``create_gateway_target`` payload for a Lambda MCP target.

    Outbound auth is ``GATEWAY_IAM_ROLE``: the gateway's own role invokes the
    function. The function resource policy should allow that role only.
    ``lambda_arn`` is supplied by the caller from the environment.
    """
    return {
        "credentialProviderConfigurations": [{"credentialProviderType": "GATEWAY_IAM_ROLE"}],
        "gatewayIdentifier": gateway_id,
        "name": target_name,
        "targetConfiguration": {
            "mcp": {
                "lambda": {
                    "lambdaArn": lambda_arn,
                    "toolSchema": {"inlinePayload": [dict(item) for item in definitions]},
                }
            }
        },
    }


def build_policy_request(
    *,
    policy_engine_id: str,
    statement: str,
    agent_version: str,
) -> dict[str, Any]:
    """Build a ``create_policy`` payload. The client token is a hash of the statement."""
    digest = hashlib.sha256(statement.encode("utf-8")).hexdigest()
    effect = "forbid" if statement.startswith("forbid") else "permit"
    version_token = _version_token(agent_version)
    return {
        "clientToken": digest,
        "definition": {"cedar": {"statement": statement}},
        "description": f"{effect} gateway tool for agent version {agent_version}",
        "name": f"{effect}-{version_token}-{digest[:12]}",
        "policyEngineId": policy_engine_id,
        "validationMode": "FAIL_ON_ANY_FINDINGS",
    }


def _version_token(agent_version: str) -> str:
    cleaned = "".join(char if char.isalnum() else "-" for char in agent_version.lower())
    token = cleaned.strip("-")[:20]
    return token or "agent"

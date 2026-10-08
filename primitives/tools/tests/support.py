"""Shared registry fixtures for tool tests."""

from collections.abc import Callable, Mapping
from typing import Any

from agentcore_tools import Policy, ToolRegistry

AGENT_VERSION = "0.1.0"
GATEWAY_ID = "gateway-local"

ECHO_SCHEMA: dict[str, Any] = {
    "additionalProperties": False,
    "properties": {"value": {"type": "string"}},
    "required": ["value"],
    "type": "object",
}

Handler = Callable[[Mapping[str, Any]], Mapping[str, Any]]


def echo_registry(
    handler: Handler,
    *,
    name: str = "echo",
    side_effecting: bool = False,
    idempotent: bool = True,
    schema: Mapping[str, Any] | None = None,
    timeout_ms: int = 10_000,
    description: str = "Echo a value.",
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.tool(
        name=name,
        schema=dict(schema or ECHO_SCHEMA),
        description=description,
        idempotent=idempotent,
        side_effecting=side_effecting,
        timeout_ms=timeout_ms,
    )(handler)
    registry.add_lambda_target("demo", tools=(name,))
    return registry


def bind(
    registry: ToolRegistry,
    *,
    tool: str = "echo",
    version: str = AGENT_VERSION,
    permit: bool = True,
    forbid: bool = False,
) -> Policy:
    policy = Policy()
    if permit:
        policy.permit(version, tool)
    if forbid:
        policy.forbid(version, tool)
    registry.bind_gateway(GATEWAY_ID, policy=policy)
    return policy

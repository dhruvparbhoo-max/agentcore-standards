"""Deny-by-default policy. Forbid wins. The handler does not run on deny."""

from collections.abc import Mapping
from typing import Any

import pytest
from agentcore_tools import ErrorClass, IdempotencyRequired, PolicyDecision, ToolRegistry
from support import AGENT_VERSION, ECHO_SCHEMA, bind, echo_registry


def _ok(args: Mapping[str, Any]) -> Mapping[str, Any]:
    return {"value": str(args["value"])}


def test_unbound_gateway_denies_without_calling_the_handler() -> None:
    calls = {"n": 0}

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["n"] += 1
        return _ok(args)

    registry = echo_registry(handler)
    result = registry.invoke_tool("echo", {"value": "x"}, agent_version=AGENT_VERSION)
    assert result.error is not None
    assert result.error.code == "policy_denied"
    assert result.error.error_class is ErrorClass.FATAL
    assert result.error.backoff_ms is None
    assert calls["n"] == 0


def test_bound_policy_denies_until_permit() -> None:
    calls = {"n": 0}

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["n"] += 1
        return _ok(args)

    registry = echo_registry(handler)
    policy = bind(registry, permit=False)
    denied = registry.invoke_tool("echo", {"value": "x"}, agent_version=AGENT_VERSION)
    assert denied.error is not None
    assert denied.error.code == "policy_denied"
    assert calls["n"] == 0
    policy.permit(AGENT_VERSION, "echo")
    allowed = registry.invoke_tool("echo", {"value": "x"}, agent_version=AGENT_VERSION)
    assert allowed.ok
    assert allowed.output == {"value": "x"}
    assert calls["n"] == 1


def test_forbid_overrides_permit() -> None:
    calls = {"n": 0}

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["n"] += 1
        return _ok(args)

    registry = echo_registry(handler)
    policy = bind(registry, forbid=True)
    assert policy.decision(AGENT_VERSION, "echo") is PolicyDecision.DENY
    result = registry.invoke_tool("echo", {"value": "x"}, agent_version=AGENT_VERSION)
    assert result.error is not None
    assert result.error.code == "policy_denied"
    assert calls["n"] == 0


def test_policy_deny_precedes_schema_rejection() -> None:
    calls = {"n": 0}

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["n"] += 1
        return _ok(args)

    registry = echo_registry(handler)
    bind(registry, permit=False)
    result = registry.invoke_tool("echo", {}, agent_version=AGENT_VERSION)
    assert result.error is not None
    assert result.error.code == "policy_denied"
    assert calls["n"] == 0


def test_permit_is_scoped_to_the_agent_version() -> None:
    calls = {"n": 0}

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["n"] += 1
        return _ok(args)

    registry = echo_registry(handler)
    bind(registry, version=AGENT_VERSION)
    result = registry.invoke_tool("echo", {"value": "x"}, agent_version="0.2.0")
    assert result.error is not None
    assert result.error.code == "policy_denied"
    assert calls["n"] == 0


def test_side_effecting_tool_without_idempotency_is_rejected() -> None:
    registry = ToolRegistry()
    with pytest.raises(IdempotencyRequired, match="idempotency"):

        @registry.tool(
            name="charge",
            schema=ECHO_SCHEMA,
            description="Charge a customer.",
            idempotent=False,
            side_effecting=True,
        )
        def charge(args: Mapping[str, Any]) -> Mapping[str, Any]:
            return {"value": str(args["value"])}

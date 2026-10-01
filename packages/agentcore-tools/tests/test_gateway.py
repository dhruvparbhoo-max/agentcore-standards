"""Gateway Lambda target wiring. MCP servers stay unimplemented."""

import json
from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from agentcore_tools import (
    DEMO_AGENT_VERSION,
    LAMBDA_TARGET,
    PUT_RECORD,
    AgentCoreGatewayClient,
    GatewayConfigError,
    LambdaContext,
    McpServerTarget,
    Policy,
    ToolConfigurationError,
    ToolRegistry,
    build_demo_registry,
    gateway_tool_name,
    make_lambda_handler,
    strip_gateway_tool_name,
)
from agentcore_tools.naming import InvalidNameError
from support import AGENT_VERSION, ECHO_SCHEMA, bind, echo_registry


def _lambda_arn() -> str:
    return "arn:" + "aws:" + "lambda:us-east-1:example:function:records"


class RecordingControl:
    def __init__(self) -> None:
        self.targets: list[dict[str, Any]] = []
        self.policies: list[dict[str, Any]] = []

    def create_gateway_target(
        self,
        *,
        gatewayIdentifier: str,
        name: str,
        targetConfiguration: Mapping[str, Any],
        credentialProviderConfigurations: Sequence[Mapping[str, str]],
    ) -> dict[str, Any]:
        self.targets.append(
            {
                "credentialProviderConfigurations": [dict(item) for item in credentialProviderConfigurations],
                "gatewayIdentifier": gatewayIdentifier,
                "name": name,
                "targetConfiguration": json.loads(json.dumps(targetConfiguration)),
            }
        )
        return {"status": "READY", "targetId": "target-local"}

    def create_policy(
        self,
        *,
        policyEngineId: str,
        name: str,
        validationMode: str,
        description: str,
        definition: Mapping[str, Any],
        clientToken: str,
    ) -> dict[str, Any]:
        self.policies.append(
            {
                "clientToken": clientToken,
                "definition": json.loads(json.dumps(definition)),
                "description": description,
                "name": name,
                "policyEngineId": policyEngineId,
                "validationMode": validationMode,
            }
        )
        return {"policyId": "policy-local", "status": "ACTIVE"}


class ConflictControl(RecordingControl):
    def create_gateway_target(
        self,
        *,
        gatewayIdentifier: str,
        name: str,
        targetConfiguration: Mapping[str, Any],
        credentialProviderConfigurations: Sequence[Mapping[str, str]],
    ) -> dict[str, Any]:
        raise _Conflict()


class _Conflict(Exception):
    def __init__(self) -> None:
        super().__init__("exists")
        self.response = {"Error": {"Code": "ConflictException"}}


def _client(control: RecordingControl) -> AgentCoreGatewayClient:
    return AgentCoreGatewayClient(
        region="us-east-1",
        gateway_id="gateway-dev",
        policy_engine_id="engine-dev",
        lambda_arn=_lambda_arn(),
        gateway_resource="gateway/records-dev",
        control=control,
    )


def test_visible_tool_name_uses_the_gateway_delimiter() -> None:
    assert gateway_tool_name("records", "put_record") == "records___put_record"
    assert strip_gateway_tool_name("records___put_record") == "put_record"


def test_mcp_server_target_is_not_configurable() -> None:
    target = McpServerTarget(name="notes", server_name="notes-server")
    with pytest.raises(ToolConfigurationError, match="Lambda"):
        target.to_configuration()
    with pytest.raises(InvalidNameError):
        McpServerTarget(name="notes", server_name="https://notes.example")


def test_bind_requires_a_lambda_target() -> None:
    registry = ToolRegistry()

    @registry.tool(name="echo", schema=ECHO_SCHEMA, description="Echo a value.")
    def echo(args: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"value": str(args["value"])}

    registry.add_mcp_server_target(name="notes", server_name="notes-server")
    with pytest.raises(ToolConfigurationError, match="Lambda"):
        registry.bind_gateway("gateway-local")


def test_lambda_dispatch_does_not_apply_gateway_policy() -> None:
    demo = build_demo_registry()
    dispatched = demo.registry.dispatch_target(
        PUT_RECORD,
        {"body": "x", "record_id": "rec-1"},
        agent_version=DEMO_AGENT_VERSION,
    )
    assert dispatched.ok
    denied = demo.registry.invoke_tool(
        PUT_RECORD,
        {"body": "x", "record_id": "rec-1"},
        agent_version=DEMO_AGENT_VERSION,
        idempotency_key="k1",
    )
    assert denied.error is not None
    assert denied.error.code == "policy_denied"
    assert demo.executions == 1


def test_lambda_handler_strips_the_target_prefix_and_dedupes() -> None:
    demo = build_demo_registry()
    handler = make_lambda_handler(demo.registry, agent_version=DEMO_AGENT_VERSION)
    context = LambdaContext(
        tool_name=gateway_tool_name(LAMBDA_TARGET, PUT_RECORD),
        gateway_id="gateway-local",
        target_id="target-local",
        request_id="request-lambda",
    )
    token = "token-should-not-leak"
    rejected = handler({"body": token, "extra": 1, "record_id": "rec-9"}, context)
    assert rejected["isError"] is True
    assert token not in json.dumps(rejected)
    first = handler({"body": "one", "record_id": "rec-9"}, context)
    second = handler({"body": "two", "record_id": "rec-9"}, context)
    assert "isError" not in first
    assert len(demo.store) == 1
    stored = demo.store.get("rec-9")
    assert stored is not None
    assert stored["body"] == "one"
    parsed = json.loads(second["content"][0]["text"])
    assert parsed["created"] is False


def test_sync_submits_lambda_target_and_cedar_permit() -> None:
    demo = build_demo_registry()
    policy = Policy()
    policy.permit(DEMO_AGENT_VERSION, PUT_RECORD)
    policy.forbid(DEMO_AGENT_VERSION, PUT_RECORD)
    demo.registry.bind_gateway("gateway-dev", policy=policy)
    control = RecordingControl()
    result = _client(control).sync(demo.registry, agent_version=DEMO_AGENT_VERSION, target_name=LAMBDA_TARGET)
    assert result.target_response["status"] == "READY"
    assert len(control.targets) == 1
    target = control.targets[0]
    assert target["credentialProviderConfigurations"] == [{"credentialProviderType": "GATEWAY_IAM_ROLE"}]
    encoded = json.dumps(target["targetConfiguration"], sort_keys=True)
    assert "inlinePayload" in encoded
    assert "additionalProperties" not in encoded
    assert PUT_RECORD in encoded
    assert len(control.policies) == 1
    statement = control.policies[0]["definition"]["cedar"]["statement"]
    assert statement.startswith("forbid")
    assert 'AgentCore::Action::"records___put_record"' in statement
    assert 'AgentCore::Gateway::"gateway/records-dev"' in statement
    assert control.policies[0]["validationMode"] == "FAIL_ON_ANY_FINDINGS"
    assert result.policy_responses[0]["policyId"] == "policy-local"


def test_sync_without_a_permit_creates_no_policy() -> None:
    demo = build_demo_registry()
    demo.registry.bind_gateway("gateway-dev", policy=Policy())
    control = RecordingControl()
    result = _client(control).sync(demo.registry, agent_version=DEMO_AGENT_VERSION, target_name=LAMBDA_TARGET)
    assert control.targets
    assert control.policies == []
    assert result.policy_responses == ()


def test_sync_treats_conflict_as_already_present() -> None:
    demo = build_demo_registry()
    policy = Policy()
    policy.permit(DEMO_AGENT_VERSION, PUT_RECORD)
    demo.registry.bind_gateway("gateway-dev", policy=policy)
    result = _client(ConflictControl()).sync(
        demo.registry,
        agent_version=DEMO_AGENT_VERSION,
        target_name=LAMBDA_TARGET,
    )
    assert result.target_response["status"] == "EXISTS"
    assert result.policy_responses


def test_sync_refuses_a_different_gateway_id() -> None:
    demo = build_demo_registry()
    demo.registry.bind_gateway("gateway-other", policy=Policy())
    with pytest.raises(GatewayConfigError, match="does not match"):
        _client(RecordingControl()).sync(demo.registry, agent_version=DEMO_AGENT_VERSION, target_name=LAMBDA_TARGET)


def test_from_env_requires_names(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AWS_REGION",
        "AGENTCORE_GATEWAY_ID",
        "AGENTCORE_POLICY_ENGINE_ID",
        "AGENTCORE_TOOLS_LAMBDA_ARN",
        "AGENTCORE_GATEWAY_RESOURCE",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(GatewayConfigError, match="missing"):
        AgentCoreGatewayClient.from_env()


def test_cedar_default_has_no_permit_statement() -> None:
    statements = Policy().cedar_statements(
        agent_version=AGENT_VERSION,
        gateway_resource="gateway/records-dev",
        actions={"echo": "demo___echo"},
    )
    assert statements == ()
    registry = echo_registry(lambda args: {"value": "x"})
    bind(registry)
    allowed = registry.invoke_tool("echo", {"value": "x"}, agent_version=AGENT_VERSION)
    assert allowed.ok

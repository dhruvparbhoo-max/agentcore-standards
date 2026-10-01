"""Real AgentCore Gateway control-plane sync. Skips unless the environment is set."""

import os

import pytest
from agentcore_tools import (
    DEMO_AGENT_VERSION,
    LAMBDA_TARGET,
    PUT_RECORD,
    AgentCoreGatewayClient,
    Policy,
    build_demo_registry,
)

_REQUIRED = (
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_REGION",
    "AGENTCORE_GATEWAY_ID",
    "AGENTCORE_POLICY_ENGINE_ID",
    "AGENTCORE_TOOLS_LAMBDA_ARN",
    "AGENTCORE_GATEWAY_RESOURCE",
)
_MISSING = any(not os.environ.get(name, "").strip() for name in _REQUIRED)


@pytest.mark.runtime
@pytest.mark.skipif(
    _MISSING,
    reason=(
        "Set AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, AGENTCORE_GATEWAY_ID, "
        "AGENTCORE_POLICY_ENGINE_ID, AGENTCORE_TOOLS_LAMBDA_ARN, and AGENTCORE_GATEWAY_RESOURCE"
    ),
)
def test_sync_demo_tool_on_agentcore_gateway() -> None:
    """Create the Lambda target and the Cedar permit for put_record.

    This does not invoke the tool through the Gateway MCP endpoint. A conflict
    from a previous sync is treated as the target already existing.
    """
    client = AgentCoreGatewayClient.from_env()
    demo = build_demo_registry()
    policy = Policy()
    policy.permit(DEMO_AGENT_VERSION, PUT_RECORD)
    gateway_id = os.environ["AGENTCORE_GATEWAY_ID"].strip()
    demo.registry.bind_gateway(gateway_id, policy=policy)
    result = client.sync(demo.registry, agent_version=DEMO_AGENT_VERSION, target_name=LAMBDA_TARGET)
    assert result.target_response
    assert result.policy_responses

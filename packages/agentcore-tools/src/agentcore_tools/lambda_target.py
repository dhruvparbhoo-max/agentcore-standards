"""Lambda handler contract for a Gateway Lambda target.

Gateway invokes the function with the tool arguments as the event and the
visible tool name in ``context.client_context.custom['bedrockAgentCoreToolName']``.
The visible name is ``{target}___{tool}``. The handler returns MCP content.
Policy has already run at the gateway; this adapter does not check it again.
"""

import json
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from agentcore_tools.naming import InvalidNameError, strip_gateway_tool_name
from agentcore_tools.registry import ToolRegistry


class LambdaClientCustom(Protocol):
    """The ``custom`` map Gateway puts on the Lambda client context."""

    custom: Mapping[str, str]


class LambdaClientContext(Protocol):
    """The subset of the Lambda context this adapter reads."""

    client_context: LambdaClientCustom


class LambdaContext:
    """In-process stand-in for the Gateway Lambda client context."""

    def __init__(
        self,
        *,
        tool_name: str,
        gateway_id: str,
        target_id: str,
        request_id: str,
        idempotency_key: str | None = None,
    ) -> None:
        custom = {
            "bedrockAgentCoreAwsRequestId": request_id,
            "bedrockAgentCoreGatewayId": gateway_id,
            "bedrockAgentCoreTargetId": target_id,
            "bedrockAgentCoreToolName": tool_name,
        }
        if idempotency_key:
            custom["bedrockAgentCoreIdempotencyKey"] = idempotency_key
        self.client_context = _Custom(custom)


class _Custom:
    def __init__(self, custom: Mapping[str, str]) -> None:
        self.custom = dict(custom)


Handler = Callable[[Mapping[str, Any], LambdaClientContext], dict[str, Any]]


def make_lambda_handler(registry: ToolRegistry, *, agent_version: str) -> Handler:
    """Return a Lambda entrypoint that routes one registry's tools.

    Deploy this function as the Gateway Lambda target. Gateway's default event
    is the tool arguments, so this adapter does not see the agent-side
    idempotency key unless ``client_context.custom['bedrockAgentCoreIdempotencyKey']``
    is set. Without that key the handler runs on every delivery. Put-if-absent
    inside the tool is the durable guard. ``invoke_tool`` still claims the key
    before it calls Gateway.
    """

    def handler(event: Mapping[str, Any], context: LambdaClientContext) -> dict[str, Any]:
        try:
            custom = context.client_context.custom
            visible = custom["bedrockAgentCoreToolName"]
            tool_name = strip_gateway_tool_name(str(visible))
        except (AttributeError, KeyError, TypeError, InvalidNameError):
            return _lambda_error("invalid_request")
        session = _custom_str(custom, "bedrockAgentCoreGatewayId") or "session-local"
        request_id = _custom_str(custom, "bedrockAgentCoreAwsRequestId")
        result = registry.dispatch_target(
            tool_name,
            event,
            agent_version=agent_version,
            runtime_session_id=session,
            request_id=request_id,
            idempotency_key=_custom_str(custom, "bedrockAgentCoreIdempotencyKey"),
        )
        if result.error is not None:
            return _lambda_error(result.error.code, result.error.message)
        text = json.dumps(result.output, sort_keys=True)
        return {"content": [{"text": text, "type": "text"}]}

    return handler


def _custom_str(custom: Mapping[str, str], key: str) -> str | None:
    value = custom.get(key)
    if isinstance(value, str) and value:
        return value
    return None


def _lambda_error(code: str, message: str | None = None) -> dict[str, Any]:
    text = message or code
    return {"content": [{"text": text, "type": "text"}], "isError": True}

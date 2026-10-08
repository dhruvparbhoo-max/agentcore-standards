"""OpenTelemetry conventions for agents on Amazon Bedrock AgentCore."""

from agentcore_tracing.attributes import (
    ATTR_AGENT_VERSION,
    ATTR_COST_SOURCE,
    ATTR_COST_TOKENS,
    ATTR_COST_USD_ESTIMATE,
    ATTR_RUNTIME_SESSION_ID,
    ATTR_SESSION_ID,
    REQUIRED_TURN_ATTRIBUTES,
    missing_required_attributes,
)
from agentcore_tracing.cost import CostEstimate, estimate_turn_cost, record_cost
from agentcore_tracing.logs import LOGGER_NAME, TurnLog, emit_turn_log
from agentcore_tracing.provider import TracerBinding, get_tracer, use_binding
from agentcore_tracing.session_id import hash_session_id
from agentcore_tracing.spans import (
    SPAN_AGENT_TURN,
    SPAN_GATEWAY_CALL,
    SPAN_GUARDRAIL_CHECK,
    SPAN_MEMORY_RETRIEVE,
    SPAN_MEMORY_WRITE,
    SPAN_MODEL_INVOKE,
    tool_span_name,
)
from agentcore_tracing.turn import turn_span

__all__ = [
    "ATTR_AGENT_VERSION",
    "ATTR_COST_SOURCE",
    "ATTR_COST_TOKENS",
    "ATTR_COST_USD_ESTIMATE",
    "ATTR_RUNTIME_SESSION_ID",
    "ATTR_SESSION_ID",
    "LOGGER_NAME",
    "REQUIRED_TURN_ATTRIBUTES",
    "SPAN_AGENT_TURN",
    "SPAN_GATEWAY_CALL",
    "SPAN_GUARDRAIL_CHECK",
    "SPAN_MEMORY_RETRIEVE",
    "SPAN_MEMORY_WRITE",
    "SPAN_MODEL_INVOKE",
    "CostEstimate",
    "TracerBinding",
    "TurnLog",
    "emit_turn_log",
    "estimate_turn_cost",
    "get_tracer",
    "hash_session_id",
    "missing_required_attributes",
    "record_cost",
    "tool_span_name",
    "turn_span",
    "use_binding",
]

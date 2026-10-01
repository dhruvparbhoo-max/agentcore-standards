"""Span name conventions. One correlated trace per user turn."""

SPAN_AGENT_TURN = "agent.turn"
SPAN_MODEL_INVOKE = "model.invoke"
SPAN_MEMORY_WRITE = "memory.write"
SPAN_MEMORY_RETRIEVE = "memory.retrieve"
SPAN_GATEWAY_CALL = "gateway.call"
SPAN_GUARDRAIL_CHECK = "guardrail.check"


def tool_span_name(tool_name: str) -> str:
    """Child span for a tool call: ``tool.<name>``."""
    if not tool_name or not tool_name.strip():
        raise ValueError("tool_name is required")
    return f"tool.{tool_name.strip()}"

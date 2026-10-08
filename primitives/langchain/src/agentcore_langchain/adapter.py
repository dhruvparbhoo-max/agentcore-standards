"""LangChain ``create_agent`` adapter for a Runtime entrypoint.

The hosted model is ``ChatBedrockConverse``. ``AGENTCORE_MEMORY_ID`` selects
LangGraph's ``AgentCoreMemorySaver`` as the thread checkpointer. That saver is
not ``agentcore_memory.MemoryClient``. Session events still go through
``MemoryClient``, which screens with the guard before a write. Without the
memory id, the checkpointer is in-process and labeled ``in-memory-not-production``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langgraph.types import Command

DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-6"
OFFLINE_CHECKPOINTER = "in-memory-not-production"
AGENTCORE_CHECKPOINTER = "agentcore-memory"
_READ_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class CheckpointerChoice:
    """Saver plus a label tests can assert."""

    saver: Any
    kind: str


@dataclass(frozen=True)
class GraphTurn:
    """One ``create_agent`` result, completed or paused for approval."""

    status: str
    text: str
    interrupt: dict[str, Any] | None
    tool_name: str | None


def build_checkpointer() -> CheckpointerChoice:
    """Pick AgentCore Memory when configured, otherwise the offline saver."""
    memory_id = os.environ.get("AGENTCORE_MEMORY_ID", "").strip()
    if not memory_id:
        from langgraph.checkpoint.memory import InMemorySaver

        return CheckpointerChoice(saver=InMemorySaver(), kind=OFFLINE_CHECKPOINTER)
    region = os.environ.get("AWS_REGION", "").strip()
    if not region:
        raise RuntimeError("AWS_REGION is required when AGENTCORE_MEMORY_ID is set")
    from langgraph_checkpoint_aws import AgentCoreMemorySaver

    saver = AgentCoreMemorySaver(memory_id, region_name=region)
    return CheckpointerChoice(saver=saver, kind=AGENTCORE_CHECKPOINTER)


def build_langchain_agent(
    model: Any,
    tools: Sequence[Any],
    *,
    system_prompt: str,
    middleware: Sequence[Any] = (),
    context_schema: type[Any] | None = None,
    checkpointer: Any | None = None,
) -> Any:
    """Assemble ``create_agent`` with a stable system prompt and a checkpointer.

    Human approval needs the checkpointer. The default is the offline saver.
    """
    saver = build_checkpointer().saver if checkpointer is None else checkpointer
    return create_agent(
        model=model,
        tools=list(tools),
        system_prompt=system_prompt,
        middleware=list(middleware),
        context_schema=context_schema,
        checkpointer=saver,
    )


def bedrock_converse_model() -> Any:
    """Chat model AgentCore Runtime hosts. Import happens on first use."""
    from botocore.config import Config as BotoConfig
    from langchain_aws import ChatBedrockConverse

    region = os.environ.get("AWS_REGION", "").strip()
    if not region:
        raise RuntimeError("AWS_REGION is required for ChatBedrockConverse on AgentCore Runtime")
    model_id = os.environ.get("BEDROCK_MODEL_ID", "").strip() or DEFAULT_MODEL_ID
    return ChatBedrockConverse(
        model=model_id,
        region_name=region,
        config=BotoConfig(read_timeout=_READ_TIMEOUT_SECONDS),
    )


def message_text(message: Any) -> str:
    """Text of one message. Content may be a string or a list of blocks."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content)


def reject_non_string_prompt(payload: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return a rejection when ``prompt`` is present and not a non-empty string.

    A missing ``prompt`` is left alone so a resume can send only ``decision``.
    A list or object is rejected here, before ``create_agent`` can treat a
    ``toolUse`` block as a tool call.
    """
    if "prompt" not in payload:
        return None
    raw = payload.get("prompt")
    if isinstance(raw, str) and raw.strip():
        return None
    if isinstance(raw, str) and not raw.strip() and payload.get("decision") is not None:
        return None
    return {
        "interrupt": None,
        "result": "Invalid input: prompt must be a non-empty string",
        "status": "rejected",
    }


def read_graph_result(result: Any, *, waiting: str) -> GraphTurn:
    """Normalize a v2 graph result or a state dict that carries ``__interrupt__``."""
    from agentcore_langchain.hitl import interrupt_view

    state, interrupts = _state_and_interrupts(result)
    if interrupts:
        body = interrupt_view(interrupts[0])
        tool_name = body.get("tool")
        name = tool_name if isinstance(tool_name, str) else None
        return GraphTurn(status="interrupted", text=waiting, interrupt=body, tool_name=name)
    messages = state.get("messages")
    if not isinstance(messages, list) or not messages:
        raise RuntimeError("LangChain agent returned no messages")
    return GraphTurn(
        status="completed",
        text=message_text(messages[-1]),
        interrupt=None,
        tool_name=_last_tool_name(messages),
    )


def resume_approval(decision: Mapping[str, Any]) -> Command[Any]:
    """LangGraph resume payload for one approve or reject decision."""
    return Command(resume={"decisions": [dict(decision)]})


def _state_and_interrupts(result: Any) -> tuple[Mapping[str, Any], list[Any]]:
    interrupts = getattr(result, "interrupts", None)
    if interrupts is not None:
        value = getattr(result, "value", {})
        state = value if isinstance(value, Mapping) else {}
        return state, list(interrupts)
    if isinstance(result, Mapping):
        raw = result.get("__interrupt__") or []
        return result, list(raw)
    raise RuntimeError("LangChain agent returned an unexpected result")


def _last_tool_name(messages: list[Any]) -> str | None:
    from langchain_core.messages import ToolMessage

    name: str | None = None
    for message in messages:
        if isinstance(message, ToolMessage) and isinstance(message.name, str) and message.name:
            name = message.name
    return name

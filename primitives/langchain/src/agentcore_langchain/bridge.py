"""Callables LangChain can pass to ``create_agent``, backed by the tool registry.

Each callable takes one JSON object string. The registry validates that object.
The string returned to the model is a compacted tool result, not the raw payload
when the payload is long. ``create_runtime_agent`` calls ``langchain.agents.create_agent``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from agentcore_context import AssembledContext
from agentcore_tools import ToolRegistry, compact_tool_output
from agentcore_tools.idempotency import args_hash

from agentcore_langchain.turn import current_turn

ToolCallable = Callable[[str], str]


def registry_callables(registry: ToolRegistry) -> list[ToolCallable]:
    """One callable per registered tool. Names and docstrings come from the registry."""
    callables: list[ToolCallable] = []
    for spec in registry.list_tools():
        name = str(spec["name"])
        description = str(spec["description"])
        callables.append(_callable(registry, name, description))
    return callables


def create_runtime_agent(*, model: Any, registry: ToolRegistry, system_prompt: str) -> Any:
    """Build a LangChain agent whose tools call ``registry.invoke_tool``.

    ``system_prompt`` should be the assembled context for the turn. The model
    object is whatever ``create_agent`` accepts. This function does not pick a
    provider.
    """
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        raise ValueError("system prompt is required")
    from langchain.agents import create_agent

    return create_agent(
        model=model,
        tools=registry_callables(registry),
        system_prompt=system_prompt,
    )


def prompt_from_context(assembled: AssembledContext) -> str:
    """Use an assembled context as the LangChain system prompt."""
    return assembled.as_system_prompt()


def _callable(registry: ToolRegistry, name: str, description: str) -> ToolCallable:
    def invoke_tool_json(arguments_json: str) -> str:
        """Run this registry tool. ``arguments_json`` is one JSON object."""
        binding = current_turn()
        args = _parse(arguments_json)
        if args is None:
            return "fatal schema_rejected"
        key = _idempotency_key(binding.session_id, name, args)
        result = registry.invoke_tool(
            name,
            args,
            agent_version=binding.agent_version,
            idempotency_key=key,
            actor_id=binding.actor_id,
            runtime_session_id=binding.session_id,
        )
        if result.error is not None:
            text = f"{result.error.error_class.value} {result.error.code}"
        else:
            text = json.dumps(result.output, sort_keys=True)
        return compact_tool_output(text, tool_name=name).text

    invoke_tool_json.__name__ = name
    invoke_tool_json.__doc__ = description
    return invoke_tool_json


def _parse(arguments_json: str) -> dict[str, Any] | None:
    if not isinstance(arguments_json, str):
        return None
    try:
        parsed: object = json.loads(arguments_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def _idempotency_key(session_id: str, tool_name: str, args: dict[str, Any]) -> str:
    safe_session = "".join(char for char in session_id if char.isalnum())[:40] or "session"
    digest = args_hash(args)[:16]
    return f"k-{safe_session}-{tool_name}-{digest}"[:128]

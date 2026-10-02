"""Guard, context assembly, and screened memory for one invoice turn.

PII card masking stays in the LangChain stack. Email, phone, and secret
shapes go through ``Guard`` first. Session text is stored only by
``MemoryClient``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from agentcore_context import StateBar, assemble_context
from agentcore_guardrails import Blocked, Guard, Sanitized
from agentcore_memory import MemoryClient
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from agent_with_tools.prompt import SYSTEM_PROMPT

_guard = Guard()
_memory: dict[str, MemoryClient] = {}


def reset_shelf() -> None:
    """Forget in-process memory clients between tests."""
    _memory.clear()


def screen_input(text: str) -> Sanitized | Blocked:
    """Screen a user prompt before the graph sees it."""
    return _guard.apply_input(text)


def screen_output(text: str) -> str:
    """Return text that may be shown. A block becomes a fixed sentence."""
    decision = _guard.apply_output(text)
    if isinstance(decision, Blocked) or not isinstance(decision, Sanitized):
        return "The reply was blocked."
    return decision.text


def remember_turn(
    *,
    agent_version: str,
    session_id: str,
    actor_id: str,
    user_text: str,
    assistant_text: str,
) -> None:
    """Store screened user and assistant text. Empty strings are skipped."""
    client = _memory.get(agent_version)
    if client is None:
        client = MemoryClient(_guard, agent_version=agent_version, environment="local")
        _memory[agent_version] = client
    if user_text.strip():
        client.create_event(session_id=session_id, actor_id=actor_id, role="user", content=user_text)
    if assistant_text.strip():
        client.create_event(
            session_id=session_id,
            actor_id=actor_id,
            role="assistant",
            content=assistant_text,
        )


class GuardMiddleware(AgentMiddleware):
    """Screen human text with ``Guard`` before later redaction hooks run."""

    tools: Sequence[Any] = ()

    def before_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        del runtime
        messages = list(state["messages"])
        updated, changed = _screen_message_list(messages)
        if not changed:
            return None
        return {"messages": updated}

    async def abefore_model(self, state: Any, runtime: Any) -> dict[str, Any] | None:
        return self.before_model(state, runtime)


class ShelfContextMiddleware(AgentMiddleware):
    """Put an assembled prompt, including the state bar, on the model request."""

    tools: Sequence[Any] = ()

    def wrap_model_call(self, request: Any, handler: Callable[[Any], Any]) -> Any:
        return handler(_with_assembled(request))

    async def awrap_model_call(self, request: Any, handler: Callable[[Any], Awaitable[Any]]) -> Any:
        return await handler(_with_assembled(request))


def _screen_message_list(messages: list[Any]) -> tuple[list[Any], bool]:
    updated: list[Any] = []
    changed = False
    for message in messages:
        content = getattr(message, "content", None)
        if isinstance(message, HumanMessage) and isinstance(content, str) and content.strip():
            decision = _guard.apply_input(content)
            if isinstance(decision, Sanitized) and decision.text != content:
                updated.append(message.model_copy(update={"content": decision.text}))
                changed = True
                continue
            if isinstance(decision, Blocked):
                updated.append(message.model_copy(update={"content": "The prompt was blocked."}))
                changed = True
                continue
        updated.append(message)
    return updated, changed


def _with_assembled(request: Any) -> Any:
    messages = list(getattr(request, "messages", ()) or ())
    human = "resume"
    calls = 0
    errors = 0
    for message in messages:
        content = getattr(message, "content", "")
        text = content if isinstance(content, str) else ""
        if isinstance(message, HumanMessage) and text.strip():
            human = text.strip()
        if isinstance(message, ToolMessage):
            calls += 1
            if '"ok": false' in text or '"ok":false' in text:
                errors += 1
    bar = StateBar(tool_calls=calls, tool_errors=errors)
    assembled = assemble_context(system=SYSTEM_PROMPT, user=human, state_bar=bar)
    status = SystemMessage(content=assembled.as_system_prompt())
    replaced = False
    updated: list[Any] = []
    for message in messages:
        if not replaced and isinstance(message, SystemMessage):
            updated.append(status)
            replaced = True
        else:
            updated.append(message)
    if not replaced:
        updated.append(status)
    return _override(request, updated)


def _override(request: Any, messages: list[Any]) -> Any:
    if hasattr(request, "override"):
        return request.override(messages=messages)
    return request

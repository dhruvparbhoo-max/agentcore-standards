"""The actor and session for the tool calls inside one Runtime turn."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar

from agentcore_identity import require_actor_id, require_session_id
from agentcore_tools.naming import require_agent_version


class TurnUnbound(Exception):
    """A registry tool ran without ``bind_turn``."""


class TurnBinding:
    """Identifiers the registry requires. The idempotency key is derived per call."""

    def __init__(self, *, actor_id: str, session_id: str, agent_version: str) -> None:
        self.actor_id = actor_id
        self.session_id = session_id
        self.agent_version = require_agent_version(agent_version)


_current: ContextVar[TurnBinding | None] = ContextVar("agentcore_langchain_turn", default=None)


def current_turn() -> TurnBinding:
    """Return the binding for this context, or raise when a tool ran outside a turn."""
    binding = _current.get()
    if binding is None:
        raise TurnUnbound("bind_turn before calling a registry tool")
    return binding


@contextmanager
def bind_turn(binding: TurnBinding) -> Iterator[None]:
    """Install ``binding`` for registry tools invoked on this context."""
    token = _current.set(binding)
    try:
        yield
    finally:
        _current.reset(token)


def turn_from_headers(
    headers: Mapping[str, str],
    *,
    agent_version: str,
    context_session_id: str | None = None,
) -> TurnBinding:
    """Build a turn from Runtime headers. A missing actor raises."""
    return TurnBinding(
        actor_id=require_actor_id(headers),
        session_id=require_session_id(headers, context_session_id=context_session_id),
        agent_version=agent_version,
    )

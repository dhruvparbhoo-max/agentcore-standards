"""In-process memory. The AgentCore Memory service adapter is not selected here.

DESIGN §7 still leaves Gateway-versus-SDK open. This client is the contract
those adapters must meet: no write without a guardrail screen, no cross-actor
read, short-term events stay on the session, long-term records are an explicit
promote.
"""

from __future__ import annotations

import threading
import uuid
from collections.abc import Mapping

from agentcore_guardrails import Blocked, Guard, Sanitized

from agentcore_memory.namespace import MemoryNamespace
from agentcore_memory.records import MemoryEvent, RetrievalHit

_ROLES = frozenset({"user", "assistant", "tool"})


class MemoryWriteDenied(Exception):
    """The guardrail blocked the write. Nothing was stored."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class MemoryClient:
    """Short-term events and long-term records for one namespace."""

    def __init__(self, guard: Guard, *, agent_version: str, environment: str) -> None:
        self._guard = guard
        self._namespace = MemoryNamespace(agent_version=agent_version, environment=environment)
        self._lock = threading.Lock()
        self._events: dict[str, MemoryEvent] = {}

    @property
    def namespace(self) -> str:
        return self._namespace.name

    def create_event(self, *, session_id: str, actor_id: str, role: str, content: str) -> MemoryEvent:
        """Screen ``content`` and store the sanitized text as a short-term event."""
        _require(session_id, "session id")
        _require(actor_id, "actor id")
        if role not in _ROLES:
            raise ValueError("invalid role")
        decision = self._guard.screen_memory_write(
            {
                "actor_id": actor_id,
                "content": content,
                "namespace": self.namespace,
                "role": role,
            }
        )
        if isinstance(decision, Blocked) or not isinstance(decision, Sanitized):
            reason = decision.reason if isinstance(decision, Blocked) else "blocked"
            raise MemoryWriteDenied(reason)
        event = MemoryEvent(
            event_id=str(uuid.uuid4()),
            session_id=session_id,
            actor_id=actor_id,
            namespace=self.namespace,
            role=role,
            content=decision.text,
            tier="stm",
            source_event_id=None,
        )
        with self._lock:
            self._events[event.event_id] = event
        return event

    def promote(self, event_id: str, *, actor_id: str) -> MemoryEvent:
        """Copy one short-term event into long-term storage after a second screen."""
        _require(actor_id, "actor id")
        with self._lock:
            source = self._events.get(event_id)
        if source is None or source.actor_id != actor_id or source.namespace != self.namespace:
            raise MemoryWriteDenied("not_found")
        if source.tier != "stm":
            raise MemoryWriteDenied("not_short_term")
        decision = self._guard.screen_memory_write(_event_mapping(source))
        if not isinstance(decision, Sanitized):
            raise MemoryWriteDenied(decision.reason if isinstance(decision, Blocked) else "blocked")
        promoted = MemoryEvent(
            event_id=str(uuid.uuid4()),
            session_id=source.session_id,
            actor_id=source.actor_id,
            namespace=source.namespace,
            role=source.role,
            content=decision.text,
            tier="ltm",
            source_event_id=source.event_id,
        )
        with self._lock:
            self._events[promoted.event_id] = promoted
        return promoted

    def list_session_events(self, session_id: str, *, actor_id: str) -> tuple[MemoryEvent, ...]:
        """Return short-term events for this session and actor only."""
        _require(session_id, "session id")
        _require(actor_id, "actor id")
        with self._lock:
            events = [
                item
                for item in self._events.values()
                if item.tier == "stm" and item.session_id == session_id and item.actor_id == actor_id
            ]
        return tuple(events)

    def retrieve(self, actor_id: str, query: str, *, namespace: str | None = None) -> tuple[RetrievalHit, ...]:
        """Lexically rank this actor's long-term records. Other actors and namespaces are absent."""
        _require(actor_id, "actor id")
        if namespace is not None and namespace != self.namespace:
            raise MemoryWriteDenied("namespace")
        tokens = _tokens(query)
        if not tokens:
            return ()
        with self._lock:
            records = [
                item
                for item in self._events.values()
                if item.tier == "ltm" and item.actor_id == actor_id and item.namespace == self.namespace
            ]
        hits: list[RetrievalHit] = []
        for item in records:
            score = _overlap(tokens, _tokens(item.content))
            if score > 0:
                hits.append(RetrievalHit(event=item, score=score))
        hits.sort(key=lambda hit: (-hit.score, hit.event.event_id))
        return tuple(hits)


def _event_mapping(event: MemoryEvent) -> Mapping[str, object]:
    return {
        "actor_id": event.actor_id,
        "content": event.content,
        "namespace": event.namespace,
        "role": event.role,
    }


def _require(value: str, label: str) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"invalid {label}")
    if any(ord(char) < 32 for char in value):
        raise ValueError(f"invalid {label}")


def _tokens(text: str) -> set[str]:
    found: set[str] = set()
    for raw in text.casefold().split():
        token = "".join(char for char in raw if char.isalnum())
        if len(token) >= 2:
            found.add(token)
    return found


def _overlap(query: set[str], document: set[str]) -> float:
    if not query or not document:
        return 0.0
    shared = query & document
    if not shared:
        return 0.0
    return len(shared) / len(query)

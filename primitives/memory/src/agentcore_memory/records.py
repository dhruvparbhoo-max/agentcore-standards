"""Records returned by the memory client. ``screened`` is set only after the guard allows the write."""

from __future__ import annotations


class MemoryEvent:
    """One stored event. ``content`` is the sanitized text, not the raw input."""

    def __init__(
        self,
        *,
        event_id: str,
        session_id: str,
        actor_id: str,
        namespace: str,
        role: str,
        content: str,
        tier: str,
        source_event_id: str | None,
    ) -> None:
        self.event_id = event_id
        self.session_id = session_id
        self.actor_id = actor_id
        self.namespace = namespace
        self.role = role
        self.content = content
        self.tier = tier
        self.source_event_id = source_event_id
        self.screened = True


class RetrievalHit:
    """A long-term record that overlapped the query. The score is lexical, not an embedding."""

    def __init__(self, *, event: MemoryEvent, score: float) -> None:
        if score <= 0:
            raise ValueError("retrieval score must be positive")
        self.event = event
        self.score = score
        self.method = "lexical"

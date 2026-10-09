"""Agent session that retrieves first. Empty search never calls the model."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace

from agentcore_agent import AgentSession, TurnResult
from agentcore_agent.build import BLOCKED_REPLY
from agentcore_guardrails import Blocked

from policy_qa.knowledge import EMPTY, inject, retrieve


class KnowledgeSession:
    """``run`` matches ``AgentSession`` so the golden scorer can use it."""

    def __init__(self, inner: AgentSession) -> None:
        self._inner = inner
        self.config = inner.config

    @property
    def release_id(self) -> str:
        return self._inner.release_id

    def run(self, prompt: str, *, session_id: str, actor_id: str) -> TurnResult:
        self._inner._check_session(session_id, actor_id)
        screened = self._inner.guard.apply_input(prompt)
        if isinstance(screened, Blocked):
            return TurnResult(
                status="blocked",
                text=BLOCKED_REPLY,
                session_id=session_id,
                release_id=self.release_id,
                blocked_reason=screened.reason,
            )
        citations = retrieve(screened.text, actor_id)
        if not citations:
            return TurnResult(status="completed", text=EMPTY, session_id=session_id, release_id=self.release_id)
        result = self._inner.run(inject(screened.text, citations), session_id=session_id, actor_id=actor_id)
        missing = [item.passage_id for item in citations if item.passage_id not in result.text]
        if missing:
            cited = " ".join(f"[{item}]" for item in missing)
            result = replace(result, text=f"{result.text} Sources: {cited}")
        return result

    def resume(self, *, session_id: str, actor_id: str, token_id: str, approved: bool, message: str = "") -> TurnResult:
        return self._inner.resume(
            session_id=session_id, actor_id=actor_id, token_id=token_id, approved=approved, message=message
        )

    def stream(self, prompt: str, *, session_id: str, actor_id: str) -> Iterator[str]:
        yield from self._inner.stream(prompt, session_id=session_id, actor_id=actor_id)

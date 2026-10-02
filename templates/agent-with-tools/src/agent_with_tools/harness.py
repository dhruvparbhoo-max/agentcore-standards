"""Bind the invoice desk entrypoint to RuntimeHarness."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agentcore_eval import (
    AgentCoreRuntimeHarness,
    InMemoryRuntimeHarness,
    InvokeResult,
    RuntimeHarness,
    SessionHandle,
    TraceBundle,
)

from agent_with_tools.entrypoint import handle_turn


class AgentWithToolsHarness:
    """RuntimeHarness for the invoice desk.

    The default inner harness calls ``handle_turn`` in-process.
    ``for_agentcore_runtime`` calls the deployed AgentCore Runtime service.
    """

    def __init__(self, inner: RuntimeHarness | None = None) -> None:
        self._inner = inner if inner is not None else InMemoryRuntimeHarness(handle_turn)

    @classmethod
    def for_agentcore_runtime(cls) -> AgentWithToolsHarness:
        """Harness that uses InvokeAgentRuntime. Requires environment credentials."""
        return cls(AgentCoreRuntimeHarness.from_env())

    def start(
        self,
        *,
        actor_id: str,
        agent_version: str,
        session_id: str | None = None,
    ) -> SessionHandle:
        return self._inner.start(actor_id=actor_id, agent_version=agent_version, session_id=session_id)

    def invoke(self, session: SessionHandle, payload: Mapping[str, Any]) -> InvokeResult:
        return self._inner.invoke(session, payload)

    def capture_traces(self, session: SessionHandle) -> TraceBundle:
        return self._inner.capture_traces(session)

    def tear_down(self, session: SessionHandle) -> None:
        self._inner.tear_down(session)

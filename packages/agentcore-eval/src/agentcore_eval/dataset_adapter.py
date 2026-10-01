"""Adapter toward the SDK on-demand dataset runner.

``OnDemandEvaluationDatasetRunner`` (bedrock-agentcore) invokes an agent, waits
for telemetry, collects CloudWatch spans, and calls Evaluate. That runner is the
later service-side eval path. Lane A does not call it.

What lands here is the invoker callable that runner accepts: one turn object
with ``payload`` and ``session_id``, returning ``AgentInvokerOutput``. A future
runtime-evals job can pass ``HarnessAgentInvoker`` as ``agent_invoker``.
"""

from collections.abc import Mapping
from typing import Any

from bedrock_agentcore.evaluation.runner.invoker_types import AgentInvokerOutput

from agentcore_eval.harness import HarnessError, RuntimeHarness, SessionHandle


class HarnessAgentInvoker:
    """Map dataset turns onto ``RuntimeHarness.start`` / ``invoke``.

    The same ``session_id`` reuses one harness session so multi-turn scenarios
    stay on one Runtime session. ``close`` calls ``tear_down`` for each session.
    """

    def __init__(self, harness: RuntimeHarness, *, actor_id: str, agent_version: str) -> None:
        self._harness = harness
        self._actor_id = actor_id
        self._agent_version = agent_version
        self._sessions: dict[str, SessionHandle] = {}

    def __call__(self, turn: Any) -> AgentInvokerOutput:
        payload = _payload_of(turn)
        session_key = _session_of(turn)
        session = self._sessions.get(session_key)
        if session is None:
            session = self._harness.start(
                actor_id=self._actor_id,
                agent_version=self._agent_version,
                session_id=session_key,
            )
            self._sessions[session_key] = session
        result = self._harness.invoke(session, payload)
        return AgentInvokerOutput(agent_output=dict(result.output))

    def close(self) -> None:
        for session in self._sessions.values():
            self._harness.tear_down(session)
        self._sessions.clear()


def load_on_demand_runner() -> type[Any]:
    """Import ``OnDemandEvaluationDatasetRunner`` so the dependency is real.

    Calling ``run`` needs AWS credentials, a dataset, and a span collector.
    The runtime-evals workflow owns that call. This loader only checks the symbol.
    """
    from bedrock_agentcore.evaluation import OnDemandEvaluationDatasetRunner

    if not hasattr(OnDemandEvaluationDatasetRunner, "run"):
        raise HarnessError("OnDemandEvaluationDatasetRunner.run is missing")
    return OnDemandEvaluationDatasetRunner


def _payload_of(turn: Any) -> Mapping[str, Any]:
    payload = getattr(turn, "payload", None)
    if payload is None and isinstance(turn, Mapping):
        payload = turn.get("payload")
    if not isinstance(payload, Mapping):
        raise HarnessError("agent invoker turn is missing a mapping payload")
    return payload


def _session_of(turn: Any) -> str:
    session_id = getattr(turn, "session_id", None)
    if session_id is None and isinstance(turn, Mapping):
        session_id = turn.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise HarnessError("agent invoker turn is missing session_id")
    return session_id

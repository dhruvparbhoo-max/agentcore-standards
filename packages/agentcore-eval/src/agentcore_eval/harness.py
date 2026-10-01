"""RuntimeHarness protocol and the evidence types it returns.

A harness is a client of one agent entrypoint. AgentCore Runtime is the managed
service that hosts ``BedrockAgentCoreApp``. Swapping a hosted container later
re-wraps the entrypoint; evals keep calling this protocol.
"""

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

_ARN_MARKER = "arn:" + "aws:"


class HarnessError(Exception):
    """The harness could not complete a lifecycle call."""


class SessionClosed(HarnessError):
    """Invoke or start targeted a session that ``tear_down`` already ended."""


class RuntimeConfigError(HarnessError):
    """Real Runtime settings are missing from the environment."""


class SessionHandle:
    """Identity of one Runtime session. One session is one actor conversation."""

    def __init__(self, *, session_id: str, actor_id: str, agent_version: str) -> None:
        if not session_id:
            raise ValueError("session_id is required")
        if not actor_id:
            raise ValueError("actor_id is required")
        if not agent_version:
            raise ValueError("agent_version is required")
        self.session_id = session_id
        self.actor_id = actor_id
        self.agent_version = agent_version


class InvokeResult:
    """Observable output of one turn."""

    def __init__(self, *, output: Mapping[str, Any], latency_ms: float) -> None:
        self.output = dict(output)
        self.latency_ms = latency_ms


class SpanRecord:
    """JSON-safe span captured for an evidence bundle."""

    def __init__(
        self,
        *,
        name: str,
        span_id: str,
        trace_id: str,
        parent_span_id: str | None,
        attributes: Mapping[str, Any],
        status: str,
    ) -> None:
        self.name = name
        self.span_id = span_id
        self.trace_id = trace_id
        self.parent_span_id = parent_span_id
        self.attributes = dict(attributes)
        self.status = status

    def as_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes,
            "name": self.name,
            "parent_span_id": self.parent_span_id,
            "span_id": self.span_id,
            "status": self.status,
            "trace_id": self.trace_id,
        }


class TraceBundle:
    """Traces and structured logs for one session."""

    def __init__(
        self,
        *,
        session_id: str,
        spans: tuple[SpanRecord, ...],
        logs: tuple[Mapping[str, Any], ...],
    ) -> None:
        self.session_id = session_id
        self.spans = spans
        self.logs = logs


@runtime_checkable
class RuntimeHarness(Protocol):
    """Thin Runtime boundary used by every eval.

    ``start`` binds a session, ``invoke`` sends one turn, ``capture_traces``
    collects OTEL spans and structured logs, ``tear_down`` ends the session.
    """

    def start(
        self,
        *,
        actor_id: str,
        agent_version: str,
        session_id: str | None = None,
    ) -> SessionHandle:
        """Provision or bind a session for ``actor_id``."""

    def invoke(self, session: SessionHandle, payload: Mapping[str, Any]) -> InvokeResult:
        """Send one turn."""

    def capture_traces(self, session: SessionHandle) -> TraceBundle:
        """Collect spans and logs for ``session``."""

    def tear_down(self, session: SessionHandle) -> None:
        """End the session. Further invokes fail. Idempotent."""


def assert_no_resource_arn(text: str) -> None:
    """Refuse to persist an ARN in an evidence bundle."""
    if _ARN_MARKER in text:
        raise HarnessError("refusing to write an evidence bundle that contains a resource ARN")

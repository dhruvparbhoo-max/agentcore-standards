"""Root span for one user turn."""

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace

from agentcore_tracing.attributes import ATTR_AGENT_VERSION, ATTR_RUNTIME_SESSION_ID
from agentcore_tracing.provider import get_tracer
from agentcore_tracing.session_id import hash_session_id
from agentcore_tracing.spans import SPAN_AGENT_TURN


@contextmanager
def turn_span(*, agent_version: str, session_id: str) -> Iterator[trace.Span]:
    """Open ``agent.turn`` with version and a hashed session id.

    Callers record cost attributes on the yielded span before the block exits.
    """
    if not agent_version:
        raise ValueError("agent_version is required")
    attributes = {
        ATTR_AGENT_VERSION: agent_version,
        ATTR_RUNTIME_SESSION_ID: hash_session_id(session_id),
    }
    with get_tracer().start_as_current_span(SPAN_AGENT_TURN, attributes=attributes) as span:
        yield span

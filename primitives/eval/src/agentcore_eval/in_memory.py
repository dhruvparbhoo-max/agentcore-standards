"""In-process RuntimeHarness.

This stands in for AgentCore Runtime during local and unit evals. It still calls
the product entrypoint. It does not stub that function's behavior.

The product Memory package is ``primitives/memory`` and is still a
stub. This module is not that client.
"""

import inspect
import json
import logging
import time
import uuid
from collections.abc import Awaitable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any, Protocol

from agentcore_tracing.logs import LOGGER_NAME
from agentcore_tracing.provider import TracerBinding, use_binding
from opentelemetry.sdk.trace import ReadableSpan

from agentcore_eval.harness import (
    HarnessError,
    InvokeResult,
    SessionClosed,
    SessionHandle,
    SpanRecord,
    TraceBundle,
)


class TurnHandler(Protocol):
    """Product entrypoint adapted to the harness call shape."""

    def __call__(
        self,
        payload: Mapping[str, Any],
        *,
        session_id: str,
        actor_id: str,
        agent_version: str,
    ) -> Mapping[str, Any] | Awaitable[Mapping[str, Any]]:
        """Handle one turn."""


class _JsonListHandler(logging.Handler):
    def __init__(self, sink: list[dict[str, Any]]) -> None:
        super().__init__()
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        try:
            parsed = json.loads(message)
        except json.JSONDecodeError:
            return
        if isinstance(parsed, dict):
            self._sink.append(parsed)


class _OpenSession:
    def __init__(self, handle: SessionHandle, binding: TracerBinding) -> None:
        self.handle = handle
        self.binding = binding
        self.logs: list[dict[str, Any]] = []
        self.ended = False
        self.started_at = datetime.now(UTC)


class InMemoryRuntimeHarness:
    """Call ``handler`` in-process and retain its spans and JSON logs."""

    def __init__(self, handler: TurnHandler) -> None:
        self._handler = handler
        self._sessions: dict[str, _OpenSession] = {}

    def start(
        self,
        *,
        actor_id: str,
        agent_version: str,
        session_id: str | None = None,
    ) -> SessionHandle:
        chosen = session_id or str(uuid.uuid4())
        existing = self._sessions.get(chosen)
        if existing is not None:
            if existing.ended:
                raise SessionClosed(f"session {chosen} is closed")
            if existing.handle.actor_id != actor_id:
                raise HarnessError(f"session {chosen} is bound to a different actor")
            return existing.handle
        handle = SessionHandle(session_id=chosen, actor_id=actor_id, agent_version=agent_version)
        self._sessions[chosen] = _OpenSession(handle, TracerBinding())
        return handle

    def invoke(self, session: SessionHandle, payload: Mapping[str, Any]) -> InvokeResult:
        state = self._require_open(session)
        started = time.perf_counter()
        with use_binding(state.binding), _capture_logs(state.logs):
            output = self._handler_call(state, payload)
            if inspect.iscoroutine(output):
                output.close()
                raise HarnessError("handler returned a coroutine; use ainvoke")
            if inspect.isawaitable(output):
                raise HarnessError("handler returned an awaitable; use ainvoke")
            return self._finish(output, started)

    async def ainvoke(self, session: SessionHandle, payload: Mapping[str, Any]) -> InvokeResult:
        """Invoke an async entrypoint. The RuntimeHarness protocol itself stays synchronous."""
        state = self._require_open(session)
        started = time.perf_counter()
        with use_binding(state.binding), _capture_logs(state.logs):
            output = self._handler_call(state, payload)
            if inspect.isawaitable(output):
                output = await output
            return self._finish(output, started)

    def capture_traces(self, session: SessionHandle) -> TraceBundle:
        state = self._require_known(session)
        spans = tuple(_span_record(span) for span in state.binding.finished())
        logs = tuple(dict(item) for item in state.logs)
        return TraceBundle(session_id=session.session_id, spans=spans, logs=logs)

    def tear_down(self, session: SessionHandle) -> None:
        state = self._sessions.get(session.session_id)
        if state is None:
            return
        state.ended = True

    def _require_known(self, session: SessionHandle) -> _OpenSession:
        state = self._sessions.get(session.session_id)
        if state is None:
            raise HarnessError(f"unknown session {session.session_id}")
        return state

    def _require_open(self, session: SessionHandle) -> _OpenSession:
        state = self._require_known(session)
        if state.ended:
            raise SessionClosed(f"session {session.session_id} is closed")
        if state.handle.actor_id != session.actor_id:
            raise HarnessError("session actor does not match the handle")
        return state

    def _handler_call(self, state: _OpenSession, payload: Mapping[str, Any]) -> Any:
        return self._handler(
            dict(payload),
            session_id=state.handle.session_id,
            actor_id=state.handle.actor_id,
            agent_version=state.handle.agent_version,
        )

    def _finish(self, output: object, started: float) -> InvokeResult:
        if not isinstance(output, Mapping):
            raise HarnessError("handler must return a mapping")
        latency_ms = (time.perf_counter() - started) * 1000
        return InvokeResult(output=output, latency_ms=latency_ms)


@contextmanager
def _capture_logs(sink: list[dict[str, Any]]) -> Iterator[None]:
    logger = logging.getLogger(LOGGER_NAME)
    handler = _JsonListHandler(sink)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    previous = logger.propagate
    logger.propagate = False
    try:
        yield
    finally:
        logger.removeHandler(handler)
        logger.propagate = previous


def _span_record(span: ReadableSpan) -> SpanRecord:
    context = span.get_span_context()
    if context is None:
        raise HarnessError("finished span is missing a span context")
    parent_id = None
    if span.parent is not None:
        parent_id = format(span.parent.span_id, "016x")
    attributes = {key: _jsonable(value) for key, value in dict(span.attributes or {}).items()}
    return SpanRecord(
        name=span.name,
        span_id=format(context.span_id, "016x"),
        trace_id=format(context.trace_id, "032x"),
        parent_span_id=parent_id,
        attributes=attributes,
        status=span.status.status_code.name,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return str(value)

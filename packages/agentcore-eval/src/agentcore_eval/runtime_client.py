"""Client of the AgentCore Runtime service.

``BedrockAgentCoreApp`` is the process the service hosts. This harness calls
``InvokeAgentRuntime`` on a runtime identifier supplied in the environment.
Identifiers are never committed.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

from agentcore_eval.harness import (
    HarnessError,
    InvokeResult,
    RuntimeConfigError,
    SessionClosed,
    SessionHandle,
    SpanRecord,
    TraceBundle,
)

_ARN_PREFIX = "arn:" + "aws:"
_MIN_SESSION_CHARS = 33
_MAX_SESSION_CHARS = 256
RUNTIME_SETTINGS: tuple[str, ...] = (
    "AWS_ACCESS_KEY_ID",
    "AWS_REGION",
    "AGENTCORE_RUNTIME_ARN",
    "AGENTCORE_SPAN_LOG_GROUP",
)


def missing_runtime_settings() -> tuple[str, ...]:
    """Environment names still empty. A real Runtime PASS needs every one of them."""
    return tuple(name for name in RUNTIME_SETTINGS if not os.environ.get(name, "").strip())


class _Readable(Protocol):
    def read(self) -> bytes:
        """Return the full response body."""


class InvokeAgentRuntimeClient(Protocol):
    """Subset of the boto3 bedrock-agentcore client used here."""

    def invoke_agent_runtime(self, **kwargs: Any) -> Mapping[str, Any]:
        """Call InvokeAgentRuntime."""


class SpanCollector(Protocol):
    """Collects service-side spans for one session. CloudWatch is the Runtime implementation."""

    def collect(
        self,
        session_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Sequence[Mapping[str, Any]]:
        """Return span dictionaries with name, attributes, and ids."""


class _Session:
    def __init__(self, handle: SessionHandle) -> None:
        self.handle = handle
        self.ended = False
        self.started_at = datetime.now(UTC)


class AgentCoreRuntimeHarness:
    """Invoke a deployed agent on AgentCore Runtime."""

    def __init__(
        self,
        *,
        runtime_arn: str,
        region: str,
        client: InvokeAgentRuntimeClient,
        qualifier: str | None = None,
        span_collector: SpanCollector | None = None,
    ) -> None:
        if not runtime_arn.startswith(_ARN_PREFIX):
            raise RuntimeConfigError("AGENTCORE_RUNTIME_ARN must be provided via the environment")
        if not region:
            raise RuntimeConfigError("AWS_REGION is required")
        self._runtime_arn = runtime_arn
        self._region = region
        self._client = client
        self._qualifier = qualifier
        self._span_collector = span_collector
        self._sessions: dict[str, _Session] = {}

    @classmethod
    def from_env(cls) -> AgentCoreRuntimeHarness:
        """Build a harness from environment variables. Raises when they are unset."""
        runtime_arn = os.environ.get("AGENTCORE_RUNTIME_ARN", "").strip()
        region = os.environ.get("AWS_REGION", "").strip()
        qualifier = os.environ.get("AGENTCORE_RUNTIME_QUALIFIER", "").strip() or None
        log_group = os.environ.get("AGENTCORE_SPAN_LOG_GROUP", "").strip()
        if not runtime_arn or not region:
            raise RuntimeConfigError("Set AGENTCORE_RUNTIME_ARN and AWS_REGION to call AgentCore Runtime")
        import boto3

        client = boto3.client("bedrock-agentcore", region_name=region)
        collector: SpanCollector | None = None
        if log_group:
            collector = CloudWatchSpanCollector(log_group=log_group, region=region)
        return cls(
            runtime_arn=runtime_arn,
            region=region,
            client=client,
            qualifier=qualifier,
            span_collector=collector,
        )

    def start(
        self,
        *,
        actor_id: str,
        agent_version: str,
        session_id: str | None = None,
    ) -> SessionHandle:
        chosen = session_id or str(uuid.uuid4())
        _require_runtime_session_id(chosen)
        existing = self._sessions.get(chosen)
        if existing is not None:
            if existing.ended:
                raise SessionClosed(f"session {chosen} is closed")
            if existing.handle.actor_id != actor_id:
                raise HarnessError(f"session {chosen} is bound to a different actor")
            return existing.handle
        handle = SessionHandle(session_id=chosen, actor_id=actor_id, agent_version=agent_version)
        self._sessions[chosen] = _Session(handle)
        return handle

    def invoke(self, session: SessionHandle, payload: Mapping[str, Any]) -> InvokeResult:
        self._require_open(session)
        kwargs: dict[str, Any] = {
            "agentRuntimeArn": self._runtime_arn,
            "payload": json.dumps(dict(payload)).encode("utf-8"),
            "runtimeSessionId": session.session_id,
        }
        if self._qualifier:
            kwargs["qualifier"] = self._qualifier
        started = datetime.now(UTC)
        response = self._client.invoke_agent_runtime(**kwargs)
        output = _decode_response(response)
        latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
        return InvokeResult(output=output, latency_ms=latency_ms)

    def capture_traces(self, session: SessionHandle) -> TraceBundle:
        state = self._require_known(session)
        if self._span_collector is None:
            return TraceBundle(session_id=session.session_id, spans=(), logs=())
        raw = self._span_collector.collect(session.session_id, state.started_at, datetime.now(UTC))
        spans = tuple(_span_from_mapping(item) for item in raw)
        return TraceBundle(session_id=session.session_id, spans=spans, logs=())

    def tear_down(self, session: SessionHandle) -> None:
        state = self._sessions.get(session.session_id)
        if state is None:
            return
        state.ended = True

    def _require_known(self, session: SessionHandle) -> _Session:
        state = self._sessions.get(session.session_id)
        if state is None:
            raise HarnessError(f"unknown session {session.session_id}")
        return state

    def _require_open(self, session: SessionHandle) -> _Session:
        state = self._require_known(session)
        if state.ended:
            raise SessionClosed(f"session {session.session_id} is closed")
        return state


class CloudWatchSpanCollector:
    """Adapter over the SDK's CloudWatch span collector.

    Used on the real Runtime path only. The local golden eval does not construct it.
    """

    def __init__(self, *, log_group: str, region: str, max_wait_seconds: int = 60) -> None:
        if not log_group:
            raise RuntimeConfigError("AGENTCORE_SPAN_LOG_GROUP is required to collect Runtime spans")
        self._log_group = log_group
        self._region = region
        self._max_wait_seconds = max_wait_seconds

    def collect(
        self,
        session_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Sequence[Mapping[str, Any]]:
        from bedrock_agentcore.evaluation import CloudWatchAgentSpanCollector

        collector = CloudWatchAgentSpanCollector(
            log_group_name=self._log_group,
            region=self._region,
            max_wait_seconds=self._max_wait_seconds,
        )
        spans = collector.collect(session_id=session_id, start_time=start_time, end_time=end_time)
        return [item for item in spans if isinstance(item, Mapping)]


def _require_runtime_session_id(session_id: str) -> None:
    length = len(session_id)
    if length < _MIN_SESSION_CHARS or length > _MAX_SESSION_CHARS:
        raise RuntimeConfigError(f"runtime session id must be {_MIN_SESSION_CHARS}-{_MAX_SESSION_CHARS} characters")


def _decode_response(response: Mapping[str, Any]) -> dict[str, Any]:
    content_type = str(response.get("contentType", ""))
    if "text/event-stream" in content_type:
        raise HarnessError("streaming Runtime responses are not decoded in lane A")
    body = response.get("response")
    if body is None or not hasattr(body, "read"):
        raise HarnessError("Runtime response did not include a readable body")
    raw = body.read()
    if not isinstance(raw, (bytes, bytearray)):
        raise HarnessError("Runtime response body was not bytes")
    decoded = json.loads(bytes(raw).decode("utf-8"))
    if not isinstance(decoded, dict):
        raise HarnessError("Runtime response must be a JSON object")
    return decoded


def _span_from_mapping(item: Mapping[str, Any]) -> SpanRecord:
    attributes = item.get("attributes") or {}
    if not isinstance(attributes, Mapping):
        attributes = {}
    parent = item.get("parent_span_id")
    return SpanRecord(
        name=str(item.get("name", "")),
        span_id=str(item.get("span_id", "")),
        trace_id=str(item.get("trace_id", "")),
        parent_span_id=None if parent is None else str(parent),
        attributes=dict(attributes),
        status=str(item.get("status", "UNSET")),
    )

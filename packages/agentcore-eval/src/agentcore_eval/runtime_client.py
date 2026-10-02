"""Client of the AgentCore Runtime service.

``BedrockAgentCoreApp`` is the process the service hosts. This harness calls
``InvokeAgentRuntime`` on a runtime identifier supplied in the environment,
forwards the actor on ``X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id``,
and reads spans plus ``agentcore.turn`` logs back from CloudWatch.
Identifiers are never committed.

``start`` binds the session id in this process. The service session begins on
the first ``invoke`` (sticky ``runtimeSessionId``). ``tear_down`` calls
``StopRuntimeSession``.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from agentcore_tracing import hash_session_id

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
# In-process ``RequestContext`` key. The service forwards the custom header below;
# Starlette stores that name in lowercase.
IN_PROCESS_ACTOR_HEADER = "x-agentcore-actor-id"
RUNTIME_ACTOR_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id"
_INVOKE_EVENT = "before-sign.bedrock-agentcore.InvokeAgentRuntime"
_HEADER_KWARG = "_agentcore_headers"
_STOPPED_CODES = frozenset({"ResourceNotFoundException", "ResourceNotFound", "NotFoundException"})
# Role credentials satisfy boto3 without an access key. A key without its secret does not.
RUNTIME_SETTINGS: tuple[str, ...] = (
    "AWS_REGION",
    "AGENTCORE_RUNTIME_ARN",
    "AGENTCORE_SPAN_LOG_GROUP",
)


def missing_runtime_settings() -> tuple[str, ...]:
    """Environment names still empty for a real Runtime run.

    Matches ``AgentCoreRuntimeHarness.from_env``. ``AWS_ACCESS_KEY_ID`` is
    required only when its pair ``AWS_SECRET_ACCESS_KEY`` is set, and the
    reverse. A role-based chain needs neither.
    """
    missing = [name for name in RUNTIME_SETTINGS if not os.environ.get(name, "").strip()]
    key = os.environ.get("AWS_ACCESS_KEY_ID", "").strip()
    secret = os.environ.get("AWS_SECRET_ACCESS_KEY", "").strip()
    if key and not secret:
        missing.append("AWS_SECRET_ACCESS_KEY")
    if secret and not key:
        missing.append("AWS_ACCESS_KEY_ID")
    return tuple(missing)


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
        """Return span dictionaries. ADOT field names are accepted."""


class LogCollector(Protocol):
    """Collects structured ``agentcore.turn`` logs for one session."""

    def collect(
        self,
        session_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Sequence[Mapping[str, Any]]:
        """Return turn-log objects. ``runtimeSessionId`` is the session hash."""


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
        log_collector: LogCollector | None = None,
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
        self._log_collector = log_collector
        self._sessions: dict[str, _Session] = {}
        self._invoke_lock = threading.Lock()

    @classmethod
    def from_env(cls) -> AgentCoreRuntimeHarness:
        """Build a harness from environment variables. Raises when they are unset."""
        missing = missing_runtime_settings()
        if missing:
            raise RuntimeConfigError("Set " + ", ".join(missing) + " to call AgentCore Runtime")
        runtime_arn = os.environ["AGENTCORE_RUNTIME_ARN"].strip()
        region = os.environ["AWS_REGION"].strip()
        qualifier = os.environ.get("AGENTCORE_RUNTIME_QUALIFIER", "").strip() or None
        span_group = os.environ["AGENTCORE_SPAN_LOG_GROUP"].strip()
        app_group = os.environ.get("AGENTCORE_APP_LOG_GROUP", "").strip() or span_group
        import boto3

        client = boto3.client("bedrock-agentcore", region_name=region)
        return cls(
            runtime_arn=runtime_arn,
            region=region,
            client=client,
            qualifier=qualifier,
            span_collector=CloudWatchSpanCollector(log_group=span_group, region=region),
            log_collector=CloudWatchTurnLogCollector(log_group=app_group, region=region),
        )

    def start(
        self,
        *,
        actor_id: str,
        agent_version: str,
        session_id: str | None = None,
    ) -> SessionHandle:
        """Bind a session id, actor, and agent version.

        The microVM session starts on the first ``invoke``, which sends this id
        as ``runtimeSessionId``. There is no separate create-session API.
        """
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
        headers = {RUNTIME_ACTOR_HEADER: session.actor_id}
        started = datetime.now(UTC)
        response = self._invoke(kwargs, headers)
        output = _decode_response(response)
        latency_ms = (datetime.now(UTC) - started).total_seconds() * 1000
        return InvokeResult(output=output, latency_ms=latency_ms)

    def capture_traces(self, session: SessionHandle) -> TraceBundle:
        state = self._require_known(session)
        end = datetime.now(UTC)
        spans: tuple[SpanRecord, ...] = ()
        logs: tuple[Mapping[str, Any], ...] = ()
        if self._span_collector is not None:
            raw = self._span_collector.collect(session.session_id, state.started_at, end)
            spans = tuple(_span_from_mapping(item) for item in raw if _looks_like_span(item))
        if self._log_collector is not None:
            logs = tuple(dict(item) for item in self._log_collector.collect(session.session_id, state.started_at, end))
        return TraceBundle(session_id=session.session_id, spans=spans, logs=logs)

    def tear_down(self, session: SessionHandle) -> None:
        """End the service session via ``StopRuntimeSession``, then reject further invokes."""
        state = self._sessions.get(session.session_id)
        if state is None or state.ended:
            return
        self._stop_service_session(session)
        state.ended = True

    def _invoke(self, kwargs: dict[str, Any], headers: Mapping[str, str]) -> Mapping[str, Any]:
        events = getattr(getattr(self._client, "meta", None), "events", None)
        if events is None:
            recorded = dict(kwargs)
            recorded[_HEADER_KWARG] = dict(headers)
            return self._client.invoke_agent_runtime(**recorded)

        def add_header(request: Any, **_ignored: Any) -> None:
            header_map = request.headers
            for name, value in headers.items():
                adder = getattr(header_map, "add_header", None)
                if callable(adder):
                    adder(name, value)
                else:
                    header_map[name] = value

        with self._invoke_lock:
            handle = events.register_first(_INVOKE_EVENT, add_header)
            try:
                return self._client.invoke_agent_runtime(**kwargs)
            finally:
                events.unregister(_INVOKE_EVENT, handle)

    def _stop_service_session(self, session: SessionHandle) -> None:
        stopper = getattr(self._client, "stop_runtime_session", None)
        if stopper is None:
            return
        kwargs: dict[str, Any] = {
            "agentRuntimeArn": self._runtime_arn,
            "runtimeSessionId": session.session_id,
        }
        if self._qualifier:
            kwargs["qualifier"] = self._qualifier
        try:
            stopper(**kwargs)
        except Exception as exc:
            if _already_stopped(exc):
                return
            raise HarnessError(f"StopRuntimeSession failed for session {session.session_id}") from exc

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

    The SDK filters ``attributes.session.id`` to the raw ``runtimeSessionId``.
    Turn spans set that attribute for this reason. ``runtime.session_id`` stays
    the truncated SHA-256. Used on the real Runtime path only.
    """

    def __init__(self, *, log_group: str, region: str, max_wait_seconds: int = 180) -> None:
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


class _LogsInsights(Protocol):
    def start_query(self, **kwargs: Any) -> Mapping[str, Any]:
        """Start a Logs Insights query."""

    def get_query_results(self, **kwargs: Any) -> Mapping[str, Any]:
        """Read one Logs Insights query."""


class CloudWatchTurnLogCollector:
    """Read ``agentcore.turn`` JSON lines from the runtime application log group.

    ``CloudWatchAgentSpanCollector`` returns ADOT span documents. Application
    logs (stdout from logger ``agentcore.turn``) live in the runtime log group,
    usually the ``runtime-logs`` stream of the same group. ``AGENTCORE_APP_LOG_GROUP``
    overrides that group when the two destinations differ.
    """

    def __init__(
        self,
        *,
        log_group: str,
        region: str,
        logs_client: _LogsInsights | None = None,
        max_wait_seconds: int = 60,
        poll_interval_seconds: float = 2.0,
    ) -> None:
        if not log_group:
            raise RuntimeConfigError("a log group is required to collect Runtime turn logs")
        self._log_group = log_group
        self._region = region
        self._logs_client = logs_client
        self._max_wait_seconds = max_wait_seconds
        self._poll_interval_seconds = poll_interval_seconds

    def collect(
        self,
        session_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Sequence[Mapping[str, Any]]:
        hashed = hash_session_id(session_id)
        client = self._client()
        deadline = time.monotonic() + self._max_wait_seconds
        query_end = end_time + timedelta(seconds=60)
        while True:
            found = _query_turn_logs(client, self._log_group, hashed, start_time, query_end)
            if found or time.monotonic() >= deadline:
                return found
            time.sleep(self._poll_interval_seconds)

    def _client(self) -> _LogsInsights:
        if self._logs_client is not None:
            return self._logs_client
        import boto3

        return cast(_LogsInsights, boto3.client("logs", region_name=self._region))


def _query_turn_logs(
    client: _LogsInsights,
    log_group: str,
    session_hash: str,
    start_time: datetime,
    end_time: datetime,
) -> list[dict[str, Any]]:
    query = (
        "fields @timestamp, @message\n"
        f'| filter @message like "{session_hash}"\n'
        '| filter @message like "actorId"\n'
        "| sort @timestamp asc\n"
        "| limit 50"
    )
    started = client.start_query(
        logGroupName=log_group,
        startTime=int(start_time.timestamp()),
        endTime=int(end_time.timestamp()),
        queryString=query,
    )
    query_id = str(started["queryId"])
    result: Mapping[str, Any] = {"status": "Running", "results": []}
    for _ in range(30):
        result = client.get_query_results(queryId=query_id)
        status = str(result.get("status", ""))
        if status == "Complete":
            break
        if status in {"Failed", "Cancelled", "Timeout"}:
            return []
        time.sleep(0.05)
    else:
        return []
    logs: list[dict[str, Any]] = []
    rows = result.get("results", [])
    if not isinstance(rows, Sequence):
        return logs
    for row in rows:
        if not isinstance(row, Sequence):
            continue
        message = _field(row, "@message")
        parsed = _parse_turn_log(message, session_hash)
        if parsed is not None:
            logs.append(parsed)
    return logs


def _field(row: Sequence[Any], name: str) -> str:
    for item in row:
        if isinstance(item, Mapping) and item.get("field") == name:
            return str(item.get("value", ""))
    return ""


def _parse_turn_log(message: str, session_hash: str) -> dict[str, Any] | None:
    start = message.find("{")
    end = message.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(message[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    if parsed.get("runtimeSessionId") != session_hash or "actorId" not in parsed:
        return None
    return parsed


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


def _looks_like_span(item: Mapping[str, Any]) -> bool:
    name = item.get("name")
    return isinstance(name, str) and bool(name)


def _span_from_mapping(item: Mapping[str, Any]) -> SpanRecord:
    parent = item.get("parent_span_id", item.get("parentSpanId"))
    status = _status_name(item.get("status", "UNSET"))
    return SpanRecord(
        name=str(item.get("name", "")),
        span_id=str(item.get("span_id", item.get("spanId", ""))),
        trace_id=str(item.get("trace_id", item.get("traceId", ""))),
        parent_span_id=None if parent in (None, "") else str(parent),
        attributes=_attributes_from_mapping(item.get("attributes")),
        status=status,
    )


def _attributes_from_mapping(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, Mapping):
        return {str(key): _coerce_attribute(value) for key, value in raw.items()}
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        parsed: dict[str, Any] = {}
        for entry in raw:
            if not isinstance(entry, Mapping) or "key" not in entry:
                continue
            parsed[str(entry["key"])] = _coerce_attribute(_otel_value(entry.get("value")))
        return parsed
    return {}


def _otel_value(value: Any) -> Any:
    if not isinstance(value, Mapping):
        return value
    for key in ("stringValue", "intValue", "doubleValue", "boolValue"):
        if key in value:
            return value[key]
    return value


def _coerce_attribute(value: Any) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit() or (stripped.startswith("-") and stripped[1:].isdigit()):
            return int(stripped)
        try:
            number = float(stripped)
        except ValueError:
            return value
        if number.is_integer():
            return int(number)
        return number
    return value


def _status_name(status: Any) -> str:
    if isinstance(status, Mapping):
        status = status.get("code", status.get("status_code", "UNSET"))
    if isinstance(status, int):
        return {0: "UNSET", 1: "OK", 2: "ERROR"}.get(status, "UNSET")
    text = str(status).upper()
    if "ERROR" in text:
        return "ERROR"
    if text in {"OK", "STATUS_CODE_OK"}:
        return "OK"
    return "UNSET"


def _already_stopped(exc: BaseException) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, Mapping):
        return False
    error = response.get("Error", {})
    if isinstance(error, Mapping) and str(error.get("Code", "")) in _STOPPED_CODES:
        return True
    meta = response.get("ResponseMetadata", {})
    return isinstance(meta, Mapping) and meta.get("HTTPStatusCode") == 404

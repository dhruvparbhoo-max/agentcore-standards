"""RuntimeHarness lifecycle on the in-memory implementation and the Runtime client."""

import json
from collections.abc import Mapping
from typing import Any

import pytest
from agentcore_eval import (
    AgentCoreRuntimeHarness,
    HarnessError,
    InMemoryRuntimeHarness,
    RuntimeConfigError,
    RuntimeHarness,
    SessionClosed,
)
from agentcore_eval.runtime_client import (
    RUNTIME_ACTOR_HEADER,
    CloudWatchSpanCollector,
    CloudWatchTurnLogCollector,
    missing_runtime_settings,
)
from agentcore_tracing import hash_session_id

_RUNTIME_ARN = "arn:" + "aws:bedrock-agentcore:us-east-1:000000000000:runtime/example"
_SESSION = "session-" + ("a" * 25)


def _handler(
    payload: Mapping[str, Any],
    *,
    session_id: str,
    actor_id: str,
    agent_version: str,
) -> Mapping[str, Any]:
    return {"echo": payload["prompt"], "session_id": session_id, "actor_id": actor_id, "version": agent_version}


def test_in_memory_harness_satisfies_protocol() -> None:
    harness = InMemoryRuntimeHarness(_handler)
    assert isinstance(harness, RuntimeHarness)


def test_sticky_session_and_actor_isolation() -> None:
    harness = InMemoryRuntimeHarness(_handler)
    first = harness.start(actor_id="actor-a", agent_version="0.1.0")
    again = harness.start(actor_id="actor-a", agent_version="0.1.0", session_id=first.session_id)
    assert again.session_id == first.session_id
    other = harness.start(actor_id="actor-b", agent_version="0.1.0")
    assert other.session_id != first.session_id
    with pytest.raises(HarnessError):
        harness.start(actor_id="actor-b", agent_version="0.1.0", session_id=first.session_id)


def test_tear_down_rejects_further_invoke() -> None:
    harness = InMemoryRuntimeHarness(_handler)
    session = harness.start(actor_id="actor-a", agent_version="0.1.0")
    result = harness.invoke(session, {"prompt": "ping"})
    assert result.output["echo"] == "ping"
    harness.tear_down(session)
    harness.tear_down(session)
    with pytest.raises(SessionClosed):
        harness.invoke(session, {"prompt": "ping"})
    with pytest.raises(SessionClosed):
        harness.start(actor_id="actor-a", agent_version="0.1.0", session_id=session.session_id)


@pytest.mark.asyncio
async def test_ainvoke_awaits_async_handler() -> None:
    async def handler(
        payload: Mapping[str, Any],
        *,
        session_id: str,
        actor_id: str,
        agent_version: str,
    ) -> Mapping[str, Any]:
        return {"echo": payload["prompt"], "session_id": session_id, "actor_id": actor_id, "version": agent_version}

    harness = InMemoryRuntimeHarness(handler)
    session = harness.start(actor_id="actor-a", agent_version="0.1.0")
    result = await harness.ainvoke(session, {"prompt": "async"})
    assert result.output["echo"] == "async"
    with pytest.raises(HarnessError):
        harness.invoke(session, {"prompt": "async"})


class _Body:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload


class _Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def invoke_agent_runtime(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(kwargs)
        body = json.dumps({"result": "pong:ping"}).encode("utf-8")
        return {"contentType": "application/json", "response": _Body(body)}


def test_runtime_client_invokes_service_and_collects_spans() -> None:
    client = _Client()
    collected: list[Mapping[str, Any]] = []

    class _Collector:
        def collect(
            self,
            session_id: str,
            start_time: object,
            end_time: object,
        ) -> list[Mapping[str, Any]]:
            del start_time, end_time
            collected.append({"session_id": session_id})
            return [
                {
                    "name": "agent.turn",
                    "span_id": "ab",
                    "trace_id": "cd",
                    "parent_span_id": None,
                    "attributes": {"agent.version": "0.1.0"},
                    "status": "OK",
                }
            ]

    harness = AgentCoreRuntimeHarness(
        runtime_arn=_RUNTIME_ARN,
        region="us-east-1",
        client=client,
        qualifier="DEFAULT",
        span_collector=_Collector(),
    )
    session = harness.start(actor_id="actor-a", agent_version="0.1.0", session_id=_SESSION)
    result = harness.invoke(session, {"prompt": "ping"})
    assert result.output["result"] == "pong:ping"
    assert client.calls[0]["agentRuntimeArn"] == _RUNTIME_ARN
    assert client.calls[0]["runtimeSessionId"] == _SESSION
    assert client.calls[0]["qualifier"] == "DEFAULT"
    bundle = harness.capture_traces(session)
    assert bundle.spans[0].name == "agent.turn"
    assert collected[0]["session_id"] == _SESSION
    harness.tear_down(session)
    with pytest.raises(SessionClosed):
        harness.invoke(session, {"prompt": "ping"})


def test_runtime_session_id_length_and_missing_arn() -> None:
    client = _Client()
    harness = AgentCoreRuntimeHarness(runtime_arn=_RUNTIME_ARN, region="us-east-1", client=client)
    with pytest.raises(RuntimeConfigError):
        harness.start(actor_id="actor-a", agent_version="0.1.0", session_id="short")
    with pytest.raises(RuntimeConfigError):
        AgentCoreRuntimeHarness(runtime_arn="not-a-runtime-id", region="us-east-1", client=client)


def test_from_env_requires_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTCORE_RUNTIME_ARN", raising=False)
    monkeypatch.delenv("AWS_REGION", raising=False)
    with pytest.raises(RuntimeConfigError):
        AgentCoreRuntimeHarness.from_env()


def test_cloudwatch_collector_requires_log_group() -> None:
    with pytest.raises(RuntimeConfigError):
        CloudWatchSpanCollector(log_group="", region="us-east-1")


def test_runtime_invoke_sends_the_custom_actor_header() -> None:
    client = _Client()
    harness = AgentCoreRuntimeHarness(runtime_arn=_RUNTIME_ARN, region="us-east-1", client=client)
    session = harness.start(actor_id="actor-golden", agent_version="0.1.0", session_id=_SESSION)
    harness.invoke(session, {"prompt": "ping"})
    headers = client.calls[0]["_agentcore_headers"]
    assert headers[RUNTIME_ACTOR_HEADER] == "actor-golden"


def test_boto_style_client_puts_the_actor_on_the_signed_request() -> None:
    client = _EventClient()
    harness = AgentCoreRuntimeHarness(runtime_arn=_RUNTIME_ARN, region="us-east-1", client=client)
    session = harness.start(actor_id="actor-golden", agent_version="0.1.0", session_id=_SESSION)
    harness.invoke(session, {"prompt": "ping"})
    assert "_agentcore_headers" not in client.kwargs
    assert client.headers[RUNTIME_ACTOR_HEADER] == "actor-golden"


def test_capture_traces_maps_adot_spans_and_turn_logs() -> None:
    client = _Client()

    class _Spans:
        def collect(self, session_id: str, start_time: object, end_time: object) -> list[dict[str, Any]]:
            del start_time, end_time
            return [
                {
                    "name": "agent.turn",
                    "spanId": "turn-1",
                    "traceId": "trace-1",
                    "status": {"code": 1},
                    "attributes": [
                        {"key": "cost.tokens", "value": {"stringValue": "4"}},
                        {"key": "runtime.session_id", "value": {"stringValue": hash_session_id(session_id)}},
                    ],
                }
            ]

    class _Logs:
        def collect(self, session_id: str, start_time: object, end_time: object) -> list[dict[str, Any]]:
            del start_time, end_time
            return [{"runtimeSessionId": hash_session_id(session_id), "actorId": "actor-golden"}]

    harness = AgentCoreRuntimeHarness(
        runtime_arn=_RUNTIME_ARN,
        region="us-east-1",
        client=client,
        span_collector=_Spans(),
        log_collector=_Logs(),
    )
    session = harness.start(actor_id="actor-golden", agent_version="0.1.0", session_id=_SESSION)
    bundle = harness.capture_traces(session)
    assert bundle.spans[0].span_id == "turn-1"
    assert bundle.spans[0].status == "OK"
    assert bundle.spans[0].attributes["cost.tokens"] == 4
    assert bundle.logs[0]["actorId"] == "actor-golden"


def test_tear_down_stops_the_service_session() -> None:
    client = _StoppingClient()
    harness = AgentCoreRuntimeHarness(runtime_arn=_RUNTIME_ARN, region="us-east-1", client=client)
    session = harness.start(actor_id="actor-a", agent_version="0.1.0", session_id=_SESSION)
    harness.tear_down(session)
    assert client.stops[0]["runtimeSessionId"] == _SESSION
    with pytest.raises(SessionClosed):
        harness.invoke(session, {"prompt": "ping"})


def test_stop_not_found_is_idempotent() -> None:
    client = _StoppingClient(missing=True)
    harness = AgentCoreRuntimeHarness(runtime_arn=_RUNTIME_ARN, region="us-east-1", client=client)
    session = harness.start(actor_id="actor-a", agent_version="0.1.0", session_id=_SESSION)
    harness.tear_down(session)
    harness.tear_down(session)
    assert len(client.stops) == 1


def test_stop_failure_leaves_the_session_open() -> None:
    client = _StoppingClient(error=True)
    harness = AgentCoreRuntimeHarness(runtime_arn=_RUNTIME_ARN, region="us-east-1", client=client)
    session = harness.start(actor_id="actor-a", agent_version="0.1.0", session_id=_SESSION)
    with pytest.raises(HarnessError, match="StopRuntimeSession"):
        harness.tear_down(session)
    result = harness.invoke(session, {"prompt": "ping"})
    assert result.output["result"] == "pong:ping"


def test_missing_runtime_settings_treats_credentials_as_a_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "AWS_REGION",
        "AGENTCORE_RUNTIME_ARN",
        "AGENTCORE_SPAN_LOG_GROUP",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AGENTCORE_RUNTIME_ARN", _RUNTIME_ARN)
    missing = missing_runtime_settings()
    assert "AGENTCORE_SPAN_LOG_GROUP" in missing
    assert "AWS_ACCESS_KEY_ID" not in missing
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "local-key")
    assert "AWS_SECRET_ACCESS_KEY" in missing_runtime_settings()


def test_from_env_requires_the_span_log_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("AGENTCORE_RUNTIME_ARN", _RUNTIME_ARN)
    monkeypatch.delenv("AGENTCORE_SPAN_LOG_GROUP", raising=False)
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    with pytest.raises(RuntimeConfigError, match="AGENTCORE_SPAN_LOG_GROUP"):
        AgentCoreRuntimeHarness.from_env()


def test_turn_log_collector_reads_the_hashed_session() -> None:
    message = json.dumps({"runtimeSessionId": hash_session_id(_SESSION), "actorId": "actor-golden"})
    client = _LogsClient(message="prefix " + message)
    collector = CloudWatchTurnLogCollector(
        log_group="runtime-logs",
        region="us-east-1",
        logs_client=client,
        max_wait_seconds=0,
    )
    found = collector.collect(_SESSION, start_time=_now(), end_time=_now())
    assert found[0]["actorId"] == "actor-golden"
    assert hash_session_id(_SESSION) in client.query


class _EventClient:
    def __init__(self) -> None:
        self.meta = _Meta()
        self.kwargs: dict[str, Any] = {}
        self.headers: dict[str, str] = {}

    def invoke_agent_runtime(self, **kwargs: Any) -> Mapping[str, Any]:
        request = _Request()
        for _event, handler in list(self.meta.events.handlers):
            handler(request)
        self.kwargs = kwargs
        self.headers = dict(request.headers)
        body = json.dumps({"result": "pong:ping"}).encode("utf-8")
        return {"contentType": "application/json", "response": _Body(body)}


class _Meta:
    def __init__(self) -> None:
        self.events = _Events()


class _Events:
    def __init__(self) -> None:
        self.handlers: list[tuple[str, Any]] = []

    def register_first(self, event: str, handler: Any) -> Any:
        self.handlers.append((event, handler))
        return handler

    def unregister(self, event: str, handler: Any) -> None:
        self.handlers = [item for item in self.handlers if item != (event, handler)]


class _Request:
    def __init__(self) -> None:
        self.headers = _Headers()


class _Headers(dict[str, str]):
    def add_header(self, name: str, value: str) -> None:
        self[name] = value


class _StoppingClient(_Client):
    def __init__(self, *, missing: bool = False, error: bool = False) -> None:
        super().__init__()
        self.stops: list[dict[str, Any]] = []
        self._missing = missing
        self._error = error

    def stop_runtime_session(self, **kwargs: Any) -> dict[str, str]:
        self.stops.append(kwargs)
        if self._missing:
            raise _ServiceError("ResourceNotFoundException")
        if self._error:
            raise _ServiceError("AccessDeniedException")
        return {"status": "STOPPED"}


class _ServiceError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class _LogsClient:
    def __init__(self, *, message: str) -> None:
        self._message = message
        self.query = ""

    def start_query(self, **kwargs: Any) -> Mapping[str, str]:
        self.query = str(kwargs["queryString"])
        return {"queryId": "q-1"}

    def get_query_results(self, **kwargs: Any) -> Mapping[str, Any]:
        del kwargs
        return {
            "status": "Complete",
            "results": [[{"field": "@message", "value": self._message}]],
        }


def _now() -> Any:
    from datetime import UTC, datetime

    return datetime.now(UTC)

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
from agentcore_eval.runtime_client import CloudWatchSpanCollector

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

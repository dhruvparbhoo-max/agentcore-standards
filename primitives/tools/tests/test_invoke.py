"""Idempotency, schema rejection, and retry classification on invoke_tool."""

import logging
import threading
from collections.abc import Mapping
from typing import Any

import pytest
from agentcore_tools import ErrorClass, FatalToolError, RetryableToolError, ToolTimeout
from agentcore_tracing import SPAN_GATEWAY_CALL, TracerBinding, hash_session_id, tool_span_name, use_binding
from opentelemetry.trace import StatusCode
from support import AGENT_VERSION, bind, echo_registry


def test_schema_rejection_does_not_call_the_handler() -> None:
    calls = {"n": 0}

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["n"] += 1
        return {"value": "x"}

    registry = echo_registry(handler)
    bind(registry)
    token = "token-should-not-leak"
    result = registry.invoke_tool(
        "echo", {"value": {"nested": token}}, agent_version=AGENT_VERSION, idempotency_key="k1"
    )
    assert result.error is not None
    assert result.error.code == "schema_rejected"
    assert result.error.error_class is ErrorClass.FATAL
    assert token not in result.error.message
    assert calls["n"] == 0


def test_double_invoke_replays_without_running_the_handler_again() -> None:
    calls = {"n": 0}

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["n"] += 1
        return {"value": str(args["value"])}

    registry = echo_registry(handler, side_effecting=True)
    bind(registry)
    args = {"value": "hello"}
    first = registry.invoke_tool("echo", args, agent_version=AGENT_VERSION, idempotency_key="k1")
    assert first.output is not None
    first.output["value"] = "mutated"
    second = registry.invoke_tool("echo", args, agent_version=AGENT_VERSION, idempotency_key="k1")
    assert calls["n"] == 1
    assert first.replayed is False
    assert second.replayed is True
    assert second.output == {"value": "hello"}


def test_same_key_with_different_arguments_is_a_conflict() -> None:
    calls = {"n": 0}

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["n"] += 1
        return {"value": str(args["value"])}

    registry = echo_registry(handler, side_effecting=True)
    bind(registry)
    registry.invoke_tool("echo", {"value": "one"}, agent_version=AGENT_VERSION, idempotency_key="k1")
    second = registry.invoke_tool("echo", {"value": "two"}, agent_version=AGENT_VERSION, idempotency_key="k1")
    assert second.error is not None
    assert second.error.code == "idempotency_conflict"
    assert second.error.error_class is ErrorClass.FATAL
    assert calls["n"] == 1


def test_side_effecting_call_without_a_key_is_fatal() -> None:
    calls = {"n": 0}

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["n"] += 1
        return {"value": str(args["value"])}

    registry = echo_registry(handler, side_effecting=True)
    bind(registry)
    result = registry.invoke_tool("echo", {"value": "x"}, agent_version=AGENT_VERSION)
    assert result.error is not None
    assert result.error.code == "idempotency_key_required"
    assert calls["n"] == 0


def test_retryable_error_is_not_cached_and_includes_backoff() -> None:
    calls = {"n": 0}

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["n"] += 1
        raise RetryableToolError("try again", backoff_ms=25)

    registry = echo_registry(handler, side_effecting=True)
    bind(registry)
    first = registry.invoke_tool("echo", {"value": "x"}, agent_version=AGENT_VERSION, idempotency_key="k1")
    second = registry.invoke_tool("echo", {"value": "x"}, agent_version=AGENT_VERSION, idempotency_key="k1")
    assert first.error is not None
    assert first.error.error_class is ErrorClass.RETRYABLE
    assert first.error.backoff_ms == 25
    assert first.replayed is False
    assert second.replayed is False
    assert calls["n"] == 2


def test_fatal_error_is_cached() -> None:
    calls = {"n": 0}

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["n"] += 1
        raise FatalToolError("nope", code="rejected")

    registry = echo_registry(handler, side_effecting=True)
    bind(registry)
    first = registry.invoke_tool("echo", {"value": "x"}, agent_version=AGENT_VERSION, idempotency_key="k1")
    second = registry.invoke_tool("echo", {"value": "x"}, agent_version=AGENT_VERSION, idempotency_key="k1")
    assert first.error is not None
    assert first.error.code == "rejected"
    assert first.error.backoff_ms is None
    assert first.error.error_class is ErrorClass.FATAL
    assert second.replayed is True
    assert second.error is not None
    assert second.error.code == "rejected"
    assert calls["n"] == 1


def test_unexpected_exception_is_fatal_and_does_not_echo_the_message() -> None:
    token = "token-should-not-leak"

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        raise RuntimeError(token)

    registry = echo_registry(handler)
    bind(registry)
    result = registry.invoke_tool("echo", {"value": "x"}, agent_version=AGENT_VERSION)
    assert result.error is not None
    assert result.error.code == "unexpected"
    assert result.error.error_class is ErrorClass.FATAL
    assert token not in result.error.message


def test_handler_timeout_is_retryable() -> None:
    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        raise ToolTimeout()

    registry = echo_registry(handler)
    bind(registry)
    result = registry.invoke_tool("echo", {"value": "x"}, agent_version=AGENT_VERSION)
    assert result.error is not None
    assert result.error.code == "timeout"
    assert result.error.error_class is ErrorClass.RETRYABLE
    assert result.error.backoff_ms == 200


def test_overlapping_same_key_does_not_run_the_handler_twice() -> None:
    started = threading.Event()
    release = threading.Event()
    calls = {"n": 0}

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["n"] += 1
        started.set()
        release.wait(timeout=5)
        return {"value": str(args["value"])}

    registry = echo_registry(handler, side_effecting=True)
    bind(registry)
    box: dict[str, Any] = {}

    def first() -> None:
        box["result"] = registry.invoke_tool(
            "echo",
            {"value": "x"},
            agent_version=AGENT_VERSION,
            idempotency_key="overlap-1",
        )

    thread = threading.Thread(target=first)
    thread.start()
    assert started.wait(timeout=2)
    second = registry.invoke_tool(
        "echo",
        {"value": "x"},
        agent_version=AGENT_VERSION,
        idempotency_key="overlap-1",
    )
    assert second.error is not None
    assert second.error.code == "idempotency_in_progress"
    assert calls["n"] == 1
    release.set()
    thread.join(timeout=5)
    first_result = box["result"]
    assert first_result.ok
    replayed = registry.invoke_tool(
        "echo",
        {"value": "x"},
        agent_version=AGENT_VERSION,
        idempotency_key="overlap-1",
    )
    assert replayed.replayed is True
    assert calls["n"] == 1


def test_deadline_does_not_start_a_second_handler() -> None:
    started = threading.Event()
    release = threading.Event()
    calls = {"n": 0}

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        del args
        calls["n"] += 1
        started.set()
        release.wait(timeout=5)
        return {"value": "late"}

    registry = echo_registry(handler, side_effecting=True, timeout_ms=50)
    bind(registry)
    first = registry.invoke_tool(
        "echo",
        {"value": "x"},
        agent_version=AGENT_VERSION,
        idempotency_key="deadline-1",
    )
    assert first.error is not None
    assert first.error.code == "timeout"
    assert started.wait(timeout=2)
    second = registry.invoke_tool(
        "echo",
        {"value": "x"},
        agent_version=AGENT_VERSION,
        idempotency_key="deadline-1",
    )
    assert second.error is not None
    assert second.error.code == "idempotency_in_progress"
    assert calls["n"] == 1
    release.set()
    replayed = None
    for _ in range(50):
        candidate = registry.invoke_tool(
            "echo",
            {"value": "x"},
            agent_version=AGENT_VERSION,
            idempotency_key="deadline-1",
        )
        if candidate.replayed:
            replayed = candidate
            break
        if candidate.error is not None and candidate.error.code == "timeout":
            break
        threading.Event().wait(0.05)
    assert replayed is not None
    assert replayed.output["value"] == "late"
    assert calls["n"] == 1


def test_deadline_is_retryable() -> None:
    started = threading.Event()
    release = threading.Event()

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        started.set()
        release.wait(timeout=5)
        return {"value": "late"}

    registry = echo_registry(handler, timeout_ms=100)
    bind(registry)
    result = registry.invoke_tool("echo", {"value": "x"}, agent_version=AGENT_VERSION)
    assert result.error is not None
    assert result.error.code == "timeout"
    assert result.error.error_class is ErrorClass.RETRYABLE
    release.set()
    assert started.wait(timeout=2)


def test_spans_and_logs_omit_arguments(caplog: pytest.LogCaptureFixture) -> None:
    token = "token-should-not-leak"
    session = "session-tools-raw-value"

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"value": str(args["value"])}

    registry = echo_registry(handler)
    bind(registry)
    binding = TracerBinding()
    caplog.set_level(logging.INFO, logger="agentcore.turn")
    with use_binding(binding):
        denied = echo_registry(handler)
        bind(denied, permit=False)
        deny_result = denied.invoke_tool(
            "echo",
            {"value": token},
            agent_version=AGENT_VERSION,
            runtime_session_id=session,
            actor_id="actor-test",
            request_id="request-deny",
        )
        allowed = registry.invoke_tool(
            "echo",
            {"value": token},
            agent_version=AGENT_VERSION,
            idempotency_key="span-1",
            runtime_session_id=session,
            actor_id="actor-test",
            request_id="request-allow",
        )
        replayed = registry.invoke_tool(
            "echo",
            {"value": token},
            agent_version=AGENT_VERSION,
            idempotency_key="span-1",
            runtime_session_id=session,
            actor_id="actor-test",
            request_id="request-replay",
        )
    assert deny_result.error is not None
    assert allowed.ok
    assert replayed.replayed is True
    finished = binding.finished()
    names = [span.name for span in finished]
    assert names.count(SPAN_GATEWAY_CALL) == 1
    assert names.count(tool_span_name("echo")) == 3
    gateway = next(span for span in finished if span.name == SPAN_GATEWAY_CALL)
    assert gateway.parent is not None
    tool_spans = [span for span in finished if span.name == tool_span_name("echo")]
    assert gateway.parent.span_id == tool_spans[1].context.span_id
    assert tool_spans[0].status.status_code is StatusCode.ERROR
    assert tool_spans[0].attributes is not None
    assert tool_spans[0].attributes["tool.error_class"] == "fatal"
    for span in finished:
        for value in (span.attributes or {}).values():
            assert token not in str(value)
            assert session not in str(value)
    text = caplog.text
    assert token not in text
    assert session not in text
    assert hash_session_id(session) in text
    assert '"toolName": "echo"' in text or '"toolName":"echo"' in text

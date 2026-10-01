"""Span shape, cost attributes, and structured logs."""

from agentcore_tracing import (
    ATTR_COST_TOKENS,
    ATTR_COST_USD_ESTIMATE,
    ATTR_RUNTIME_SESSION_ID,
    SPAN_AGENT_TURN,
    SPAN_MODEL_INVOKE,
    CostEstimate,
    TracerBinding,
    TurnLog,
    emit_turn_log,
    estimate_turn_cost,
    get_tracer,
    hash_session_id,
    missing_required_attributes,
    record_cost,
    tool_span_name,
    turn_span,
    use_binding,
)


def test_tool_span_name() -> None:
    assert tool_span_name("lookup") == "tool.lookup"


def test_missing_cost_attribute_is_reported() -> None:
    missing = missing_required_attributes({"agent.version": "0.1.0", "runtime.session_id": "abc"})
    assert ATTR_COST_TOKENS in missing
    assert ATTR_COST_USD_ESTIMATE in missing


def test_zero_cost_counts_as_present() -> None:
    attributes = {
        "agent.version": "0.1.0",
        "runtime.session_id": "abc",
        "cost.tokens": 0,
        "cost.usd_estimate": 0.0,
    }
    assert missing_required_attributes(attributes) == ()


def test_session_hash_is_stable_and_not_reversible_text() -> None:
    raw = "session-1234567890"
    hashed = hash_session_id(raw)
    assert hashed == hash_session_id(raw)
    assert hashed != raw
    assert len(hashed) == 32


def test_turn_span_is_parent_of_model_invoke_and_carries_cost() -> None:
    binding = TracerBinding()
    session_id = "session-golden"
    with use_binding(binding), turn_span(agent_version="0.1.0", session_id=session_id) as span:
        with get_tracer().start_as_current_span(SPAN_MODEL_INVOKE) as model_span:
            cost = estimate_turn_cost("ping", "pong:ping")
            record_cost(model_span, cost)
        record_cost(span, cost)

    finished = {span.name: span for span in binding.finished()}
    turn = finished[SPAN_AGENT_TURN]
    model = finished[SPAN_MODEL_INVOKE]
    assert model.parent is not None
    assert model.parent.span_id == turn.context.span_id
    assert model.context.trace_id == turn.context.trace_id
    assert missing_required_attributes(dict(turn.attributes or {})) == ()
    assert turn.attributes is not None
    assert turn.attributes[ATTR_RUNTIME_SESSION_ID] == hash_session_id(session_id)
    tokens = turn.attributes[ATTR_COST_TOKENS]
    assert isinstance(tokens, int) and tokens >= 1


def test_negative_cost_is_rejected() -> None:
    try:
        CostEstimate(tokens=-1, usd_estimate=0.0)
    except ValueError as exc:
        assert "tokens" in str(exc)
    else:
        raise AssertionError("negative tokens must fail")


def test_turn_log_fields() -> None:
    payload = emit_turn_log(
        TurnLog(
            runtime_session_id="sess-1",
            actor_id="actor-1",
            agent_version="0.1.0",
            request_id="req-1",
            latency_ms=1.25,
            error_class=None,
        )
    )
    assert payload["runtimeSessionId"] == "sess-1"
    assert payload["actorId"] == "actor-1"
    assert payload["agentVersion"] == "0.1.0"
    assert payload["requestId"] == "req-1"
    assert payload["latencyMs"] == 1.25
    assert payload["errorClass"] is None
    assert "toolName" not in payload

"""Golden eval for the minimal agent.

Runs against whichever RuntimeHarness the suite injects. The default test uses
the in-memory harness, which calls the real entrypoint. Point the same eval at
AgentCore Runtime with ``MinimalAgentHarness.for_agentcore_runtime`` when
credentials exist (see the template README).
"""

from agentcore_eval import Eval, EvalContext, RuntimeHarness
from agentcore_tracing import (
    ATTR_COST_TOKENS,
    ATTR_RUNTIME_SESSION_ID,
    SPAN_AGENT_TURN,
    SPAN_MODEL_INVOKE,
    hash_session_id,
    missing_required_attributes,
)

_ACTOR_ID = "actor-golden"


def _setup(harness: RuntimeHarness, ctx: EvalContext) -> None:
    ctx.actor_id = _ACTOR_ID
    ctx.session = harness.start(actor_id=ctx.actor_id, agent_version=ctx.agent_version)


def _act(harness: RuntimeHarness, ctx: EvalContext) -> None:
    session = ctx.session
    if session is None:
        raise AssertionError("setup did not bind a session")
    ctx.results.append(harness.invoke(session, {"prompt": "ping"}))
    ctx.results.append(harness.invoke(session, {"prompt": "again"}))


def _assert(harness: RuntimeHarness, ctx: EvalContext) -> None:
    session = ctx.session
    if session is None:
        raise AssertionError("session missing")
    if len(ctx.results) != 2:
        raise AssertionError(f"expected 2 turns, got {len(ctx.results)}")
    first = ctx.results[0].output.get("result")
    second = ctx.results[1].output.get("result")
    if first != "pong:ping" or second != "pong:again":
        raise AssertionError(f"unexpected completions: {first!r}, {second!r}")

    bundle = harness.capture_traces(session)
    turns = [span for span in bundle.spans if span.name == SPAN_AGENT_TURN]
    models = [span for span in bundle.spans if span.name == SPAN_MODEL_INVOKE]
    if len(turns) != 2 or len(models) != 2:
        raise AssertionError(f"expected 2 turn and 2 model spans, got {len(turns)} and {len(models)}")

    hashed = hash_session_id(session.session_id)
    by_id = {span.span_id: span for span in bundle.spans}
    for turn in turns:
        missing = missing_required_attributes(turn.attributes)
        if missing:
            raise AssertionError(f"turn span missing cost or identity attributes: {missing}")
        if turn.attributes.get(ATTR_RUNTIME_SESSION_ID) != hashed:
            raise AssertionError("runtime.session_id on the span must be the hash, not the raw id")
        tokens = turn.attributes.get(ATTR_COST_TOKENS)
        if not isinstance(tokens, int) or tokens < 1:
            raise AssertionError(f"cost.tokens must be a positive int, got {tokens!r}")
    for model in models:
        parent = by_id.get(model.parent_span_id or "")
        if parent is None or parent.name != SPAN_AGENT_TURN or parent.trace_id != model.trace_id:
            raise AssertionError("model.invoke must be a child of agent.turn in the same trace")

    if len(bundle.logs) != 2:
        raise AssertionError(f"expected 2 structured logs, got {len(bundle.logs)}")
    request_ids: set[str] = set()
    for record in bundle.logs:
        if record.get("runtimeSessionId") != session.session_id:
            raise AssertionError("log runtimeSessionId drifted from the session")
        if record.get("actorId") != _ACTOR_ID or record.get("agentVersion") != ctx.agent_version:
            raise AssertionError("log actor or agent version did not match the session")
        request_id = record.get("requestId")
        if not isinstance(request_id, str) or not request_id:
            raise AssertionError("log requestId is required")
        request_ids.add(request_id)
        if not isinstance(record.get("latencyMs"), (int, float)):
            raise AssertionError("log latencyMs is required")
        if record.get("errorClass") is not None:
            raise AssertionError(f"golden turn logged an error: {record.get('errorClass')}")
    if len(request_ids) != 2:
        raise AssertionError("each turn needs its own requestId")


EVAL = Eval(
    name="minimal-agent.golden-turn",
    rubric=(
        "Two turns on one fresh session return the deterministic pong completions, "
        "each turn span carries cost attributes and a hashed session id, model.invoke "
        "is a child of agent.turn, and structured logs carry session, actor, version, "
        "and request id."
    ),
    setup=_setup,
    act=_act,
    assert_=_assert,
)

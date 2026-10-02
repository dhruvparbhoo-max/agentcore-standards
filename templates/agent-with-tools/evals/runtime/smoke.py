"""Runtime smoke for a deployed invoice desk.

This file is not the deterministic grader. A live model will not match the
scripted invoice line. The check is that InvokeAgentRuntime returned a turn
and that the trace contains ``agent.turn`` with cost attributes.
"""

from agentcore_eval import Eval, EvalContext, RuntimeHarness
from agentcore_tracing import SPAN_AGENT_TURN, missing_required_attributes

_ACTOR_ID = "actor-golden"


def _setup(harness: RuntimeHarness, ctx: EvalContext) -> None:
    ctx.actor_id = _ACTOR_ID
    ctx.session = harness.start(actor_id=ctx.actor_id, agent_version=ctx.agent_version)


def _act(harness: RuntimeHarness, ctx: EvalContext) -> None:
    session = ctx.session
    if session is None:
        raise AssertionError("setup did not bind a session")
    ctx.results.append(
        harness.invoke(
            session,
            {
                "prompt": "Fetch invoice INV-1001.",
                "tenant_id": "acme",
                "user_id": _ACTOR_ID,
            },
        )
    )


def _assert(harness: RuntimeHarness, ctx: EvalContext) -> None:
    session = ctx.session
    if session is None:
        raise AssertionError("session missing")
    if len(ctx.results) != 1:
        raise AssertionError(f"expected 1 turn, got {len(ctx.results)}")
    output = ctx.results[0].output
    status = output.get("status")
    if status not in {"completed", "interrupted"}:
        raise AssertionError(f"runtime turn status was {status!r}")
    result = output.get("result")
    if not isinstance(result, str) or not result.strip():
        raise AssertionError(f"runtime turn returned no text: {output!r}")
    bundle = harness.capture_traces(session)
    turns = [span for span in bundle.spans if span.name == SPAN_AGENT_TURN]
    if not turns:
        raise AssertionError("runtime trace did not include agent.turn")
    missing = missing_required_attributes(turns[0].attributes)
    if missing:
        raise AssertionError(f"runtime turn span missing attributes: {missing}")


EVAL = Eval(
    name="agent-with-tools.runtime-smoke",
    rubric=(
        "InvokeAgentRuntime returns a completed or interrupted turn with text, and "
        "the collected trace includes agent.turn with cost attributes. This does not "
        "grade invoice facts. A missing trace is a failure, not a skip."
    ),
    setup=_setup,
    act=_act,
    assert_=_assert,
)

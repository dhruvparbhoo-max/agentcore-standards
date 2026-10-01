"""AgentCore Runtime entrypoint for the minimal agent.

``BedrockAgentCoreApp`` is what AgentCore Runtime hosts (``POST /invocations``).
Evals do not boot this server. ``handle_turn`` adapts ``invoke`` to
``RuntimeHarness``, which calls it in-process or via ``InvokeAgentRuntime``
after the same code is deployed.

No tools and no Memory. The completion is deterministic so the golden eval has
an observable result without a model credential.
"""

import time
import uuid
from collections.abc import Mapping
from typing import Any

from agentcore_tracing import (
    SPAN_MODEL_INVOKE,
    TurnLog,
    emit_turn_log,
    estimate_turn_cost,
    get_tracer,
    record_cost,
    turn_span,
)
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.runtime.context import RequestContext

AGENT_VERSION = "0.1.0"
ACTOR_ID_HEADER = "x-agentcore-actor-id"

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    """Handle one Runtime turn. ``prompt`` must be a string."""
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError("prompt must be a non-empty string")
    session_id = context.session_id or ""
    if not session_id:
        raise ValueError("runtime session_id is required")
    headers = context.request_headers or {}
    actor_id = headers.get(ACTOR_ID_HEADER) or "unknown"
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    error_class: str | None = None
    try:
        completion = _run_turn(prompt, session_id)
        return {"result": completion}
    except Exception as exc:
        error_class = type(exc).__name__
        raise
    finally:
        emit_turn_log(
            TurnLog(
                runtime_session_id=session_id,
                actor_id=actor_id,
                agent_version=AGENT_VERSION,
                request_id=request_id,
                latency_ms=(time.perf_counter() - started) * 1000,
                error_class=error_class,
            )
        )


def complete_prompt(prompt: str) -> str:
    """Deterministic completion. The golden eval asserts the ``pong:`` prefix."""
    return f"pong:{prompt.strip()}"


def handle_turn(
    payload: Mapping[str, Any],
    *,
    session_id: str,
    actor_id: str,
    agent_version: str,
) -> Mapping[str, Any]:
    """Adapt the Runtime entrypoint to the in-memory harness call shape."""
    if agent_version != AGENT_VERSION:
        raise ValueError(f"agent_version {agent_version} does not match deployed {AGENT_VERSION}")
    context = RequestContext(
        session_id=session_id,
        request_headers={ACTOR_ID_HEADER: actor_id},
        request=None,
    )
    result = invoke(dict(payload), context)
    if not isinstance(result, Mapping):
        raise TypeError("entrypoint must return a mapping")
    return result


def _run_turn(prompt: str, session_id: str) -> str:
    with turn_span(agent_version=AGENT_VERSION, session_id=session_id) as span:
        with get_tracer().start_as_current_span(SPAN_MODEL_INVOKE) as model_span:
            completion = complete_prompt(prompt)
            cost = estimate_turn_cost(prompt, completion)
            record_cost(model_span, cost)
        record_cost(span, cost)
        return completion

"""AgentCore Runtime entrypoint for the invoice desk.

AgentCore Runtime hosts ``BedrockAgentCoreApp``. ``POST /invocations`` calls
``invoke``. The body of the turn is a LangChain ``create_agent`` graph built
by ``agentcore_langchain``.

``prompt`` must be a non-empty string. A list or object is rejected before the
graph runs, so a ``toolUse`` block in the payload cannot dispatch a tool.
A resume sends ``decision`` of ``approve`` or ``reject`` on the same session.
``edit`` and ``respond`` are not accepted: edit can change the idempotency key,
and respond would look like a successful write.
"""

import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from agentcore_guardrails import Blocked, Sanitized
from agentcore_identity import LOCAL_ACTOR_HEADER, require_actor_id, require_session_id
from agentcore_langchain import (
    TurnBinding,
    bind_turn,
    parse_approval,
    read_graph_result,
    reject_non_string_prompt,
    resume_approval,
)
from agentcore_langchain.turn import TurnUnbound, current_turn
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

from agent_with_tools.agent import hosted_agent
from agent_with_tools.approvals import issue_for_interrupt, settle
from agent_with_tools.context import CallerContext
from agent_with_tools.shelf import remember_turn, screen_input, screen_output
from agent_with_tools.tools import bind_request_id, reset_request_id
from agent_with_tools.version import AGENT_VERSION

TENANT_HEADER = "x-agentcore-tenant-id"
USER_HEADER = "x-agentcore-user-id"
REJECT_MESSAGE = "The note was not filed. Do not retry submit_invoice_note unless the operator asks again."

app = BedrockAgentCoreApp()

AgentFactory = Callable[[], Any]
_agent_factory: AgentFactory = hosted_agent
_agent: Any = None


def set_agent_factory(factory: AgentFactory) -> None:
    """Install the graph used by the next turn. Tests use this. Runtime does not."""
    global _agent_factory, _agent
    _agent_factory = factory
    _agent = None


def reset_agent_factory() -> None:
    """Restore the hosted ChatBedrockConverse agent."""
    set_agent_factory(hosted_agent)


def get_agent() -> Any:
    """Build the LangChain harness once per process."""
    global _agent
    if _agent is None:
        _agent = _agent_factory()
    return _agent


@app.entrypoint
def invoke(payload: dict[str, Any], context: RequestContext) -> dict[str, Any]:
    """Handle one Runtime turn.

    A new turn requires a string ``prompt``. A resume requires ``decision``
    (``approve`` or ``reject``) and may omit ``prompt``. ``tenant_id`` comes
    from the payload or ``x-agentcore-tenant-id``. ``user_id`` falls back to
    the actor id.
    """
    headers = context.request_headers or {}
    session_id = require_session_id(headers, context_session_id=context.session_id)
    actor_id = require_actor_id(headers)
    try:
        version = current_turn().agent_version
    except TurnUnbound:
        version = AGENT_VERSION
    binding = TurnBinding(actor_id=actor_id, session_id=session_id, agent_version=version)
    request_id = str(uuid.uuid4())
    started = time.perf_counter()
    error_class: str | None = None
    tool_name: str | None = None
    request_token = bind_request_id(request_id)
    try:
        with bind_turn(binding):
            rejected = reject_non_string_prompt(payload)
            if rejected is not None:
                error_class = "RejectedPrompt"
                return rejected
            decision = parse_approval(payload.get("decision"), reject_message=REJECT_MESSAGE)
            if decision is not None:
                approver = _text_field(payload, "approver_id")
                if approver is None:
                    raise ValueError("approver_id is required")
                settle(session_id=session_id, approver_id=approver, approved=decision["type"] == "approve")
            caller = _caller(payload, headers, actor_id)
            prompt = _prompt(payload, decision)
            if decision is None:
                screened = screen_input(prompt)
                if isinstance(screened, Blocked) or not isinstance(screened, Sanitized):
                    error_class = "BlockedPrompt"
                    return {
                        "interrupt": None,
                        "result": "The prompt was blocked.",
                        "status": "rejected",
                    }
                prompt = screened.text
            outcome = _run_turn(
                prompt=prompt,
                decision=decision,
                session_id=session_id,
                actor_id=actor_id,
                caller=caller,
                agent_version=version,
            )
            tool_name = outcome["tool_name"]
            shown = screen_output(str(outcome["result"]))
            remember_turn(
                agent_version=version,
                session_id=session_id,
                actor_id=actor_id,
                user_text=prompt,
                assistant_text=shown,
            )
            return {
                "interrupt": outcome["interrupt"],
                "result": shown,
                "status": outcome["status"],
            }
    except Exception as exc:
        error_class = type(exc).__name__
        raise
    finally:
        reset_request_id(request_token)
        elapsed_ms = (time.perf_counter() - started) * 1000
        emit_turn_log(
            TurnLog(
                actor_id=actor_id,
                agent_version=version,
                error_class=error_class,
                latency_ms=elapsed_ms,
                request_id=request_id,
                runtime_session_id=session_id,
                tool_name=tool_name,
            )
        )


def handle_turn(
    payload: Mapping[str, Any],
    *,
    session_id: str,
    actor_id: str,
    agent_version: str,
) -> Mapping[str, Any]:
    """Adapt the Runtime entrypoint to the harness call shape.

    The harness version is the allowlist key. A session started on another
    version still runs the graph, and Gateway policy denies the tools.
    """
    binding = TurnBinding(actor_id=actor_id, session_id=session_id, agent_version=agent_version)
    with bind_turn(binding):
        context = RequestContext(
            session_id=session_id,
            request_headers={LOCAL_ACTOR_HEADER: actor_id},
            request=None,
        )
        result = invoke(dict(payload), context)
    if not isinstance(result, Mapping):
        raise TypeError("entrypoint must return a mapping")
    return result


def _run_turn(
    *,
    prompt: str,
    decision: dict[str, Any] | None,
    session_id: str,
    actor_id: str,
    caller: CallerContext,
    agent_version: str,
) -> dict[str, Any]:
    agent = get_agent()
    config = {"configurable": {"thread_id": session_id, "actor_id": actor_id}}
    with turn_span(agent_version=agent_version, session_id=session_id) as span:
        with get_tracer().start_as_current_span(SPAN_MODEL_INVOKE) as model_span:
            if decision is None:
                graph_input: Any = {"messages": [{"role": "user", "content": prompt}]}
                cost_input = prompt
            else:
                graph_input = resume_approval(decision)
                cost_input = str(decision["type"])
            result = agent.invoke(graph_input, config=config, context=caller, version="v2")
            turn = read_graph_result(result, waiting="")
            text = turn.text
            if turn.status == "interrupted":
                label = turn.tool_name or "tool"
                text = f"Waiting for approval before {label} runs."
                arguments = {}
                if isinstance(turn.interrupt, dict) and isinstance(turn.interrupt.get("arguments"), dict):
                    arguments = turn.interrupt["arguments"]
                if turn.tool_name:
                    issue_for_interrupt(
                        session_id=session_id,
                        actor_id=actor_id,
                        tool_name=turn.tool_name,
                        arguments=arguments,
                    )
            cost = estimate_turn_cost(cost_input, text)
            record_cost(model_span, cost)
        record_cost(span, cost)
        return {
            "interrupt": turn.interrupt,
            "result": text,
            "status": turn.status,
            "tool_name": turn.tool_name,
        }


def _caller(payload: Mapping[str, Any], headers: Mapping[str, str], actor_id: str) -> CallerContext:
    tenant = _text_field(payload, "tenant_id") or _header(headers, TENANT_HEADER)
    if tenant is None:
        raise ValueError("tenant_id is required")
    user = _text_field(payload, "user_id") or _header(headers, USER_HEADER) or _nonempty(actor_id)
    if user is None:
        raise ValueError("user_id is required")
    return CallerContext(user_id=user, tenant_id=tenant)


def _prompt(payload: Mapping[str, Any], decision: dict[str, Any] | None) -> str:
    raw = payload.get("prompt")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    if decision is not None:
        return ""
    raise ValueError("prompt must be a non-empty string")


def _text_field(payload: Mapping[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name and isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _nonempty(value: str) -> str | None:
    cleaned = value.strip()
    if cleaned and cleaned != "unknown":
        return cleaned
    return None

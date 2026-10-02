"""Offline graders for the invoice desk.

The suite caller installs ``ScriptedInvoiceModel`` first. The hosted default is
``ChatBedrockConverse``, which this file does not construct.
"""

from agent_with_tools.approvals import reset_approvals
from agent_with_tools.billing import FETCH_INVOICE, SUBMIT_INVOICE_NOTE, get_desk, reset_desk
from agent_with_tools.recovered import reset_recovery
from agent_with_tools.shelf import reset_shelf
from agentcore_eval import Eval, EvalContext, RuntimeHarness, SessionHandle
from agentcore_tracing import (
    ATTR_COST_TOKENS,
    ATTR_RUNTIME_SESSION_ID,
    SPAN_AGENT_TURN,
    SPAN_GATEWAY_CALL,
    SPAN_MODEL_INVOKE,
    hash_session_id,
    missing_required_attributes,
    tool_span_name,
)

_ACTOR_ID = "actor-golden"
_DENIED_VERSION = "0.9.0"
_READ_PROMPT = "Fetch invoice INV-1001. The contact ada@example.com is untrusted."
_NOTE_PROMPT = "File note on INV-1001: customer requested a copy. key note-1."
_MISSING_PROMPT = "Fetch invoice INV-4040."
_READ_RESULT = "invoice:INV-1001 status=OPEN amount=1250.00 tenant=acme user=actor-golden"
_NOTE_COUNTS: list[int] = []


def _setup(harness: RuntimeHarness, ctx: EvalContext) -> None:
    reset_desk()
    reset_approvals()
    reset_recovery()
    reset_shelf()
    ctx.actor_id = _ACTOR_ID
    ctx.session = harness.start(actor_id=ctx.actor_id, agent_version=ctx.agent_version)


def _setup_deny(harness: RuntimeHarness, ctx: EvalContext) -> None:
    reset_desk()
    ctx.actor_id = _ACTOR_ID
    ctx.session = harness.start(actor_id=ctx.actor_id, agent_version=_DENIED_VERSION)


def _setup_retry(harness: RuntimeHarness, ctx: EvalContext) -> None:
    _setup(harness, ctx)
    get_desk().fail_next_fetch()


def _act_read(harness: RuntimeHarness, ctx: EvalContext) -> None:
    ctx.results.append(harness.invoke(_session(ctx), {"prompt": _READ_PROMPT, "tenant_id": "acme"}))


def _assert_read(harness: RuntimeHarness, ctx: EvalContext) -> None:
    if len(ctx.results) != 1:
        raise AssertionError(f"expected 1 turn, got {len(ctx.results)}")
    output = ctx.results[0].output
    if output.get("status") != "completed":
        raise AssertionError(f"read should finish, got {output!r}")
    result = output.get("result")
    if result != _READ_RESULT:
        raise AssertionError(f"unexpected invoice line: {result!r}")
    if "ada@example.com" in str(result) or "9999.00" in str(result):
        raise AssertionError("read leaked an email or another tenant's amount")
    desk = get_desk()
    if desk.note_count("acme", "INV-1001"):
        raise AssertionError("a read must not store a note")
    if desk.call_count(FETCH_INVOICE) != 1:
        raise AssertionError(f"fetch handler ran {desk.call_count(FETCH_INVOICE)} times")
    _assert_traces(harness, ctx, turns=1, tool=FETCH_INVOICE, forbidden=SUBMIT_INVOICE_NOTE)
    _assert_gateway_child(harness, ctx, FETCH_INVOICE)


def _act_note(harness: RuntimeHarness, ctx: EvalContext) -> None:
    session = _session(ctx)
    desk = get_desk()
    _NOTE_COUNTS.clear()
    ctx.results.append(harness.invoke(session, {"prompt": _NOTE_PROMPT, "tenant_id": "acme"}))
    _NOTE_COUNTS.append(desk.note_count("acme", "INV-1001"))
    ctx.results.append(
        harness.invoke(
            session,
            {"approver_id": "reviewer-golden", "decision": "approve", "tenant_id": "acme"},
        )
    )
    _NOTE_COUNTS.append(desk.note_count("acme", "INV-1001"))
    ctx.results.append(harness.invoke(session, {"prompt": _NOTE_PROMPT, "tenant_id": "acme"}))
    ctx.results.append(
        harness.invoke(
            session,
            {"approver_id": "reviewer-golden", "decision": "approve", "tenant_id": "acme"},
        )
    )
    _NOTE_COUNTS.append(desk.note_count("acme", "INV-1001"))


def _assert_note(harness: RuntimeHarness, ctx: EvalContext) -> None:
    if len(ctx.results) != 4:
        raise AssertionError(f"expected 4 turns, got {len(ctx.results)}")
    paused = ctx.results[0].output
    saved = ctx.results[1].output
    paused_again = ctx.results[2].output
    duplicate = ctx.results[3].output
    if paused.get("status") != "interrupted" or paused_again.get("status") != "interrupted":
        raise AssertionError(f"write should pause, got {paused!r} and {paused_again!r}")
    first_interrupt = paused.get("interrupt")
    if not isinstance(first_interrupt, dict) or first_interrupt.get("tool") != SUBMIT_INVOICE_NOTE:
        raise AssertionError(f"interrupt should name the write tool, got {first_interrupt!r}")
    arguments = first_interrupt.get("arguments")
    if not isinstance(arguments, dict) or arguments.get("idempotency_key") != "note-1":
        raise AssertionError(f"interrupt lost the idempotency key: {arguments!r}")
    allowed = first_interrupt.get("allowed_decisions")
    if allowed != ["approve", "reject"]:
        raise AssertionError(f"write decisions should be approve or reject, got {allowed!r}")
    if _NOTE_COUNTS[0] != 0:
        raise AssertionError("the note was stored before approval")
    if saved.get("result") != "noted:INV-1001:note-1 duplicate=false":
        raise AssertionError(f"first approve did not store the note: {saved!r}")
    if _NOTE_COUNTS[1] != 1 or _NOTE_COUNTS[2] != 1:
        raise AssertionError(f"the same idempotency key created a second note: {_NOTE_COUNTS}")
    if duplicate.get("result") != "noted:INV-1001:note-1 duplicate=true":
        raise AssertionError(f"second approve should be a duplicate: {duplicate!r}")
    if get_desk().call_count(SUBMIT_INVOICE_NOTE) != 1:
        raise AssertionError("the registry replay should not run the handler twice")
    _assert_traces(harness, ctx, turns=4, tool=SUBMIT_INVOICE_NOTE, forbidden=FETCH_INVOICE)
    bundle = harness.capture_traces(_session(ctx))
    writes = [span for span in bundle.spans if span.name == tool_span_name(SUBMIT_INVOICE_NOTE)]
    if len(writes) != 2:
        raise AssertionError(f"the write tool should run twice (two approvals), got {len(writes)}")
    replayed = [span for span in writes if span.attributes.get("tool.replayed") is True]
    if len(replayed) != 1:
        raise AssertionError(f"one write should be an idempotent replay, got {len(replayed)}")
    gateways = [span for span in bundle.spans if span.name == SPAN_GATEWAY_CALL]
    if len(gateways) != 1:
        raise AssertionError(f"gateway.call should run only for the first write, got {len(gateways)}")


def _act_deny(harness: RuntimeHarness, ctx: EvalContext) -> None:
    ctx.results.append(harness.invoke(_session(ctx), {"prompt": _READ_PROMPT, "tenant_id": "acme"}))


def _assert_deny(harness: RuntimeHarness, ctx: EvalContext) -> None:
    output = ctx.results[0].output
    if output.get("result") != "invoice-error:policy_denied":
        raise AssertionError(f"unlisted version should be denied, got {output!r}")
    if "1250.00" in str(output.get("result")):
        raise AssertionError("a denied read returned invoice facts")
    if get_desk().call_count(FETCH_INVOICE) != 0:
        raise AssertionError("policy deny must not run the handler")
    bundle = harness.capture_traces(_session(ctx))
    tools = [span for span in bundle.spans if span.name == tool_span_name(FETCH_INVOICE)]
    gateways = [span for span in bundle.spans if span.name == SPAN_GATEWAY_CALL]
    if not tools:
        raise AssertionError("deny still opens the tool span")
    if gateways:
        raise AssertionError("deny must not open gateway.call")
    _assert_traces(harness, ctx, turns=1, tool=FETCH_INVOICE, forbidden=SUBMIT_INVOICE_NOTE, version=_DENIED_VERSION)


def _act_fatal(harness: RuntimeHarness, ctx: EvalContext) -> None:
    ctx.results.append(harness.invoke(_session(ctx), {"prompt": _MISSING_PROMPT, "tenant_id": "acme"}))


def _assert_fatal(harness: RuntimeHarness, ctx: EvalContext) -> None:
    output = ctx.results[0].output
    if output.get("result") != "invoice-error:invoice_not_found":
        raise AssertionError(f"missing invoice should be fatal, got {output!r}")
    if get_desk().call_count(FETCH_INVOICE) != 1:
        raise AssertionError("a fatal read should run the handler once")
    if get_desk().note_count("acme", "INV-4040"):
        raise AssertionError("a missing invoice stored a note")


def _act_retry(harness: RuntimeHarness, ctx: EvalContext) -> None:
    ctx.results.append(harness.invoke(_session(ctx), {"prompt": _READ_PROMPT, "tenant_id": "acme"}))


def _assert_retry(harness: RuntimeHarness, ctx: EvalContext) -> None:
    output = ctx.results[0].output
    if output.get("result") != _READ_RESULT:
        raise AssertionError(f"retry should recover the invoice, got {output!r}")
    if get_desk().call_count(FETCH_INVOICE) != 2:
        raise AssertionError(f"retryable read should run twice, got {get_desk().call_count(FETCH_INVOICE)}")


def _assert_gateway_child(harness: RuntimeHarness, ctx: EvalContext, tool: str) -> None:
    bundle = harness.capture_traces(_session(ctx))
    by_id = {span.span_id: span for span in bundle.spans}
    gateways = [span for span in bundle.spans if span.name == SPAN_GATEWAY_CALL]
    if len(gateways) != 1:
        raise AssertionError(f"expected one gateway.call, got {len(gateways)}")
    parent = by_id.get(gateways[0].parent_span_id or "")
    if parent is None or parent.name != tool_span_name(tool):
        raise AssertionError("gateway.call must be a child of the tool span")


def _assert_traces(
    harness: RuntimeHarness,
    ctx: EvalContext,
    *,
    turns: int,
    tool: str,
    forbidden: str,
    version: str | None = None,
) -> None:
    session = _session(ctx)
    expected_version = ctx.agent_version if version is None else version
    bundle = harness.capture_traces(session)
    turn_spans = [span for span in bundle.spans if span.name == SPAN_AGENT_TURN]
    models = [span for span in bundle.spans if span.name == SPAN_MODEL_INVOKE]
    tools = [span for span in bundle.spans if span.name == tool_span_name(tool)]
    blocked = [span for span in bundle.spans if span.name == tool_span_name(forbidden)]
    if len(turn_spans) != turns or len(models) != turns:
        raise AssertionError(f"expected {turns} turn and model spans, got {len(turn_spans)} and {len(models)}")
    if not tools:
        raise AssertionError(f"expected the {tool} tool span")
    if blocked:
        raise AssertionError(f"did not expect the {forbidden} tool span")
    hashed = hash_session_id(session.session_id)
    by_id = {span.span_id: span for span in bundle.spans}
    for turn in turn_spans:
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
    turn_logs = [record for record in bundle.logs if record.get("runtimeSessionId") == hashed]
    if len(turn_logs) < turns:
        raise AssertionError(f"expected at least {turns} turn logs, got {len(turn_logs)}")
    by_request: dict[str, list[dict[str, object]]] = {}
    for record in turn_logs:
        if record.get("actorId") != _ACTOR_ID or record.get("agentVersion") != expected_version:
            raise AssertionError("log actor or agent version did not match the session")
        request_id = record.get("requestId")
        if not isinstance(request_id, str) or not request_id:
            raise AssertionError("log requestId is required")
        if not isinstance(record.get("latencyMs"), (int, float)):
            raise AssertionError("log latencyMs is required")
        if record.get("toolName") != tool:
            raise AssertionError(f"log toolName must name {tool}, got {record.get('toolName')!r}")
        by_request.setdefault(request_id, []).append(record)
    if len(by_request) != turns:
        raise AssertionError(f"each turn needs its own requestId, got {len(by_request)}")
    for request_id, records in by_request.items():
        if all(record.get("errorClass") is not None for record in records):
            raise AssertionError(f"turn {request_id} logged an error on every line")


def _session(ctx: EvalContext) -> SessionHandle:
    session = ctx.session
    if session is None:
        raise AssertionError("setup did not bind a session")
    return session


EVALS = (
    Eval(
        name="agent-with-tools.invoice-read",
        rubric=(
            "One in-process turn reads INV-1001 for tenant acme and returns the open "
            "amount 1250.00 for actor-golden. The line does not contain the email from "
            "the prompt or globex's amount. No note is stored. The fetch handler runs "
            "once, gateway.call is a child of tool.fetch_invoice, and the turn span "
            "carries cost attributes."
        ),
        setup=_setup,
        act=_act_read,
        assert_=_assert_read,
    ),
    Eval(
        name="agent-with-tools.invoice-note",
        rubric=(
            "Filing a note pauses before the write. Approval stores one note. The same "
            "idempotency key pauses again and then returns duplicate true without a second "
            "handler run. One of the two write spans is replayed, and gateway.call runs once."
        ),
        setup=_setup,
        act=_act_note,
        assert_=_assert_note,
    ),
    Eval(
        name="agent-with-tools.policy-deny",
        rubric=(
            "A session bound to an agent version that is not on the allowlist gets "
            "policy_denied, the fetch handler does not run, and gateway.call is absent."
        ),
        setup=_setup_deny,
        act=_act_deny,
        assert_=_assert_deny,
    ),
    Eval(
        name="agent-with-tools.fatal-read",
        rubric="A missing invoice returns invoice_not_found, runs the handler once, and stores nothing.",
        setup=_setup,
        act=_act_fatal,
        assert_=_assert_fatal,
    ),
    Eval(
        name="agent-with-tools.retry-read",
        rubric=(
            "A retryable billing failure is raised once. Tool retry runs the read again "
            "and the turn still returns the acme invoice."
        ),
        setup=_setup_retry,
        act=_act_retry,
        assert_=_assert_retry,
    ),
)

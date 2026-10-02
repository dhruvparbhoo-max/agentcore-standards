"""LangChain tools that call the billing desk through ``invoke_tool``.

The model sees invoice id, note, and idempotency key. Tenant and user come
from ``CallerContext``. Retryable registry results go through
``run_with_recovery``. A write consumes an ``ApprovalGate`` token first.
A fatal result is JSON and is not retried.
"""

import json
from contextvars import ContextVar, Token
from typing import Any

from agentcore_langchain.turn import current_turn
from agentcore_tools import ErrorClass, ToolResult
from langchain.tools import ToolRuntime, tool

from agent_with_tools.approvals import consume_write
from agent_with_tools.billing import FETCH_INVOICE, SUBMIT_INVOICE_NOTE, get_desk
from agent_with_tools.context import CallerContext
from agent_with_tools.recovered import invoke_with_recovery

_request_id: ContextVar[str | None] = ContextVar("agent_with_tools_request_id", default=None)


def bind_request_id(request_id: str) -> Token[str | None]:
    """Share the entrypoint request id with registry tool logs for this turn."""
    return _request_id.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous request id."""
    _request_id.reset(token)


class RetryableToolError(Exception):
    """The billing call failed in a way that is safe to repeat.

    Recovery retries this type once inside the tool. A missing invoice is not
    this error. The tool returns that as JSON with ``retryable`` false.
    """


@tool
def fetch_invoice(invoice_id: str, runtime: ToolRuntime[CallerContext]) -> str:
    """Read one invoice for the tenant already in runtime context.

    Returns JSON. ``ok`` true includes status and amount. ``ok`` false with
    ``retryable`` false means the id is missing for this tenant; do not retry.
    The same id always returns the same invoice. Do not pass a tenant id.
    """
    caller = _caller(runtime)
    binding = current_turn()
    result = invoke_with_recovery(
        get_desk().registry,
        FETCH_INVOICE,
        {
            "invoice_id": invoice_id,
            "tenant_id": caller.tenant_id,
            "user_id": caller.user_id,
        },
        agent_version=binding.agent_version,
        actor_id=caller.user_id,
        runtime_session_id=binding.session_id,
        request_id=_request_id.get(),
    )
    return _encode(result, invoice_id=invoice_id, tenant_id=caller.tenant_id)


@tool
def submit_invoice_note(
    invoice_id: str,
    note: str,
    idempotency_key: str,
    runtime: ToolRuntime[CallerContext],
) -> str:
    """Write a customer note on an invoice. A human approves this before it runs.

    ``idempotency_key`` is required. The same tenant, invoice, and key store
    one note. A repeat call returns ``duplicate`` true and does not create a
    second note. Do not pass a tenant id. Validation failures are not retryable.
    """
    caller = _caller(runtime)
    binding = current_turn()
    arguments = {
        "idempotency_key": idempotency_key,
        "invoice_id": invoice_id,
        "note": note,
    }
    consume_write(
        session_id=binding.session_id,
        actor_id=binding.actor_id,
        tool_name=SUBMIT_INVOICE_NOTE,
        arguments=arguments,
    )
    result = invoke_with_recovery(
        get_desk().registry,
        SUBMIT_INVOICE_NOTE,
        {
            **arguments,
            "tenant_id": caller.tenant_id,
            "user_id": caller.user_id,
        },
        agent_version=binding.agent_version,
        idempotency_key=idempotency_key,
        actor_id=caller.user_id,
        runtime_session_id=binding.session_id,
        request_id=_request_id.get(),
    )
    return _encode(result, invoice_id=invoice_id, tenant_id=caller.tenant_id)


def _caller(runtime: ToolRuntime[CallerContext]) -> CallerContext:
    caller = runtime.context
    if caller is None or not caller.tenant_id.strip() or not caller.user_id.strip():
        raise ValueError("tenant_id and user_id are required in runtime context")
    return caller


def _encode(result: ToolResult, *, invoice_id: str, tenant_id: str) -> str:
    error = result.error
    if error is not None:
        if error.error_class is ErrorClass.RETRYABLE:
            raise RetryableToolError(error.message)
        body: dict[str, Any] = {
            "error": error.code,
            "invoice_id": invoice_id.strip(),
            "ok": False,
            "retryable": False,
            "tenant_id": tenant_id,
        }
        return json.dumps(body, sort_keys=True)
    output = dict(result.output or {})
    output["ok"] = True
    output["retryable"] = False
    if result.replayed:
        output["duplicate"] = True
    return json.dumps(output, sort_keys=True)

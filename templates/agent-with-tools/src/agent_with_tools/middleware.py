"""Invoice-desk middleware. Approval, guard, and context come from the shelf."""

from typing import Any

from agentcore_langchain import agent_middleware

from agent_with_tools.billing import FETCH_INVOICE, SUBMIT_INVOICE_NOTE
from agent_with_tools.shelf import GuardMiddleware, ShelfContextMiddleware

_WRITE = "Filing an invoice note writes to the billing record."


def production_middleware() -> list[Any]:
    """Middleware every hosted graph and every offline test graph shares.

    Retryable billing errors are handled by ``invoke_with_recovery``, not by
    a second retry of the same exception in this stack.
    """
    return agent_middleware(
        read_tools=(FETCH_INVOICE,),
        write_tools={SUBMIT_INVOICE_NOTE: _WRITE},
        before_redaction=(GuardMiddleware(), ShelfContextMiddleware()),
    )

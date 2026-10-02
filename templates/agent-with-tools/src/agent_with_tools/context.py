"""Who is calling the invoice desk.

LangChain passes this object as ``context`` on ``invoke``. Tools read it from
``ToolRuntime``. The model does not choose the tenant from the sentence.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CallerContext:
    """Immutable caller identity for one turn."""

    user_id: str
    tenant_id: str

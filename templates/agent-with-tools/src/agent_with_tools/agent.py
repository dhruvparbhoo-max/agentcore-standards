"""Invoice desk graph. Assembly lives in ``agentcore_langchain``."""

from typing import Any

from agentcore_langchain import bedrock_converse_model, build_langchain_agent, message_text

from agent_with_tools.context import CallerContext
from agent_with_tools.middleware import production_middleware
from agent_with_tools.prompt import SYSTEM_PROMPT
from agent_with_tools.tools import fetch_invoice, submit_invoice_note

__all__ = ["bedrock_model", "build_agent", "hosted_agent", "message_text"]


def build_agent(
    model: Any,
    tools: list[Any] | None = None,
    *,
    checkpointer: Any | None = None,
    middleware: list[Any] | None = None,
) -> Any:
    """Bind the invoice tools, prompt, caller schema, and shared middleware."""
    chosen = [fetch_invoice, submit_invoice_note] if tools is None else list(tools)
    stack = production_middleware() if middleware is None else list(middleware)
    return build_langchain_agent(
        model,
        chosen,
        system_prompt=SYSTEM_PROMPT,
        middleware=stack,
        context_schema=CallerContext,
        checkpointer=checkpointer,
    )


def bedrock_model() -> Any:
    """Chat model AgentCore Runtime hosts. Offline tests pass a different model."""
    return bedrock_converse_model()


def hosted_agent() -> Any:
    """The agent AgentCore Runtime hosts."""
    return build_agent(bedrock_model())

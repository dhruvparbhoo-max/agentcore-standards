"""Prompt headings, middleware policy, and PII redaction."""

from __future__ import annotations

from typing import Any

from agent_with_tools.agent import build_agent, message_text
from agent_with_tools.billing import FETCH_INVOICE, SUBMIT_INVOICE_NOTE
from agent_with_tools.context import CallerContext
from agent_with_tools.middleware import production_middleware
from agent_with_tools.prompt import PROMPT_HEADINGS, SYSTEM_PROMPT
from agentcore_langchain import TurnBinding, bind_turn
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class _EchoModel(BaseChatModel):
    """Returns the last human text so a test can see redaction."""

    @property
    def _llm_type(self) -> str:
        return "echo-invoice-desk"

    def bind_tools(self, tools: Any, **kwargs: Any) -> _EchoModel:
        del tools, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        text = ""
        for message in messages:
            if isinstance(message, HumanMessage) and isinstance(message.content, str):
                text = message.content
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])


def test_prompt_keeps_its_headings() -> None:
    for heading in PROMPT_HEADINGS:
        assert heading in SYSTEM_PROMPT


def test_write_is_the_only_approval_gate() -> None:
    stack = production_middleware()
    hitl = stack[0]
    assert FETCH_INVOICE not in hitl.interrupt_on
    write = hitl.interrupt_on[SUBMIT_INVOICE_NOTE]
    assert write["allowed_decisions"] == ["approve", "reject"]


def test_email_and_card_do_not_reach_the_model() -> None:
    binding = TurnBinding(actor_id="user-1", session_id="session-pii-001", agent_version="0.1.0")
    with bind_turn(binding):
        agent = build_agent(_EchoModel())
        caller = CallerContext(user_id="user-1", tenant_id="acme")
        config = {"configurable": {"thread_id": "session-pii-001", "actor_id": "user-1"}}
        email = agent.invoke(
            {"messages": [{"role": "user", "content": "Reach me at ada@example.com today."}]},
            config=config,
            context=caller,
            version="v2",
        )
        card = agent.invoke(
            {"messages": [{"role": "user", "content": "Card 4111111111111111 is not for the note."}]},
            config=config,
            context=caller,
            version="v2",
        )
    email_text = message_text(email["messages"][-1] if isinstance(email, dict) else email.value["messages"][-1])
    card_state = card["messages"] if isinstance(card, dict) else card.value["messages"]
    card_text = message_text(card_state[-1])
    assert "ada@example.com" not in email_text
    assert "[redacted-email]" in email_text
    assert "4111111111111111" not in card_text

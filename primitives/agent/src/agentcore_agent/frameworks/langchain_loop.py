"""``framework: create_agent``. LangChain's tool-calling loop is the default.

Risky tools pause through LangGraph's interrupt (``HumanInTheLoopMiddleware``).
The checkpointer keeps the paused thread so ``resume`` continues it. Model
providers stay outside: the caller passes the chat model.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping, Sequence
from typing import Any

from agentcore_langchain import build_langchain_agent, message_text, read_graph_result, resume_approval
from agentcore_langchain.hitl import approval_middleware
from langchain.agents.middleware import ModelCallLimitMiddleware
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import StructuredTool

from agentcore_agent.frameworks.base import LoopOutcome, ToolSpec, risky_reviews
from agentcore_agent.scripted import Script


class LangChainLoop:
    framework = "create_agent"

    def __init__(
        self,
        *,
        model: Any,
        tools: Sequence[ToolSpec],
        system_prompt: str,
        max_steps: int,
        checkpointer: Any | None = None,
    ) -> None:
        reviews = risky_reviews(tuple(tools))
        middleware: list[Any] = []
        if reviews:
            reads = [tool.name for tool in tools if not tool.risky]
            middleware.append(approval_middleware(write_tools=reviews, read_tools=reads))
        middleware.append(ModelCallLimitMiddleware(run_limit=max_steps, exit_behavior="end"))
        if checkpointer is None:
            from langgraph.checkpoint.memory import InMemorySaver

            checkpointer = InMemorySaver()
        self._max_steps = max_steps
        self._graph = build_langchain_agent(
            model,
            [_to_langchain(tool) for tool in tools],
            system_prompt=system_prompt,
            middleware=middleware,
            checkpointer=checkpointer,
        )

    def invoke(self, prompt: str, *, thread_id: str) -> LoopOutcome:
        result = self._graph.invoke(
            {"messages": [{"role": "user", "content": prompt}]}, config=self._config(thread_id), version="v2"
        )
        return self._outcome(result, thread_id)

    def resume(self, *, approved: bool, message: str, thread_id: str) -> LoopOutcome:
        decision: dict[str, Any] = {"type": "approve"} if approved else {"type": "reject", "message": message}
        result = self._graph.invoke(resume_approval(decision), config=self._config(thread_id), version="v2")
        return self._outcome(result, thread_id)

    def stream(self, prompt: str, *, thread_id: str) -> Iterator[str]:
        for chunk, _meta in self._graph.stream(
            {"messages": [{"role": "user", "content": prompt}]},
            config=self._config(thread_id),
            stream_mode="messages",
        ):
            if isinstance(chunk, AIMessage):
                text = message_text(chunk)
                if text:
                    yield text

    def _config(self, thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}, "recursion_limit": max(8, self._max_steps * 4)}

    def _outcome(self, result: Any, thread_id: str) -> LoopOutcome:
        turn = read_graph_result(result, waiting="")
        if turn.status == "interrupted" and turn.interrupt is not None:
            arguments = turn.interrupt.get("arguments")
            return LoopOutcome(
                status="interrupted",
                text="",
                tool=turn.tool_name,
                arguments=arguments if isinstance(arguments, Mapping) else {},
            )
        state = self._graph.get_state(self._config(thread_id))
        messages = state.values.get("messages", []) if state is not None else []
        called = tuple(m.name for m in messages if isinstance(m, ToolMessage) and isinstance(m.name, str))
        return LoopOutcome(status="completed", text=turn.text, tools_called=called)


def _to_langchain(tool: ToolSpec) -> StructuredTool:
    def run(**kwargs: Any) -> str:
        result = tool.handler(kwargs)
        return result if isinstance(result, str) else json.dumps(result, sort_keys=True, default=str)

    return StructuredTool.from_function(
        func=run,
        name=tool.name,
        description=tool.description,
        args_schema=dict(tool.input_schema),
    )


class ScriptedChatModel(BaseChatModel):
    """LangChain face of ``Script``. Offline only."""

    script: Script

    @property
    def _llm_type(self) -> str:
        return "agentcore-scripted"

    def bind_tools(self, tools: Sequence[Any], *, tool_choice: str | None = None, **kwargs: Any) -> ScriptedChatModel:
        del tools, tool_choice, kwargs
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del stop, run_manager, kwargs
        human_index = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
        tail = messages[human_index + 1 :]
        tool_messages = [m for m in tail if isinstance(m, ToolMessage)]
        if tool_messages:
            last = tool_messages[-1]
            reply = AIMessage(content=self.script.answer(str(last.name), message_text(last)))
            return ChatResult(generations=[ChatGeneration(message=reply)])
        user_text = message_text(messages[human_index]) if human_index >= 0 else ""
        tool, args, text = self.script.first_reply(user_text)
        if tool is None:
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])
        call = {"name": tool, "args": args, "id": f"call-{len(messages)}", "type": "tool_call"}
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="", tool_calls=[call]))])

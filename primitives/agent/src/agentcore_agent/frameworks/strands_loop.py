"""``framework: strands``. The code alternative to ``create_agent``.

Risky tools pause through a ``BeforeToolCallEvent`` hook that raises a Strands
interrupt. ``resume`` answers the interrupt on the same agent object. A Runtime
session is one microVM, so one agent per session id is kept in this process.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import Any

from strands import Agent
from strands.hooks import BeforeToolCallEvent, HookCallback, HookProvider, HookRegistry
from strands.models.model import Model
from strands.tools.tools import PythonAgentTool
from strands.types.interrupt import InterruptResponseContent

from agentcore_agent.frameworks.base import LoopOutcome, LoopUsage, ToolSpec
from agentcore_agent.scripted import Script

APPROVE = "approve"


class ApprovalHook(HookProvider):
    """Interrupt before a risky tool. Anything but ``approve`` cancels the call."""

    def __init__(self, risky: Mapping[str, str]) -> None:
        self._risky = dict(risky)

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.check)

    def check(self, event: BeforeToolCallEvent) -> None:
        name = event.tool_use["name"]
        if name not in self._risky:
            return
        reason = {"tool": name, "arguments": dict(event.tool_use.get("input") or {}), "review": self._risky[name]}
        response = event.interrupt(f"approval:{name}", reason=reason)
        if response != APPROVE:
            event.cancel_tool = response if isinstance(response, str) and response else "rejected by reviewer"


class StepLimitHook(HookProvider):
    """Cancel tool calls past ``lifecycle.max_steps``. The model then has to answer."""

    def __init__(self, max_steps: int) -> None:
        self._max = max_steps
        self.count = 0

    def register_hooks(self, registry: HookRegistry, **kwargs: Any) -> None:
        registry.add_callback(BeforeToolCallEvent, self.check)

    def check(self, event: BeforeToolCallEvent) -> None:
        self.count += 1
        if self.count > self._max:
            event.cancel_tool = "step limit reached"


class StrandsLoop:
    framework = "strands"

    def __init__(
        self,
        *,
        model: Any,
        tools: Sequence[ToolSpec],
        system_prompt: str,
        max_steps: int,
    ) -> None:
        self._model = model
        self._tools = tuple(tools)
        self._system_prompt = system_prompt
        self._max_steps = max_steps
        self._risky = {tool.name: f"{tool.action}: {tool.description}" for tool in self._tools if tool.risky}
        self._agents: dict[str, Agent] = {}
        self._pending: dict[str, str] = {}
        self._seen: dict[str, tuple[int, int, int]] = {}

    def invoke(self, prompt: str, *, thread_id: str) -> LoopOutcome:
        agent = self._agent(thread_id)
        return self._outcome(agent(prompt), thread_id)

    def resume(self, *, approved: bool, message: str, thread_id: str) -> LoopOutcome:
        agent = self._agents.get(thread_id)
        interrupt_id = self._pending.pop(thread_id, None)
        if agent is None or interrupt_id is None:
            raise RuntimeError("no paused turn for this session")
        response = APPROVE if approved else (message or "rejected by reviewer")
        answer: list[InterruptResponseContent] = [
            {"interruptResponse": {"interruptId": interrupt_id, "response": response}}
        ]
        return self._outcome(agent(answer), thread_id)

    def stream(self, prompt: str, *, thread_id: str) -> Iterator[str]:
        agent = self._agent(thread_id)

        async def collect() -> list[str]:
            chunks: list[str] = []
            async for event in agent.stream_async(prompt):
                data = event.get("data") if isinstance(event, dict) else None
                if isinstance(data, str) and data:
                    chunks.append(data)
            return chunks

        yield from asyncio.run(collect())

    def _agent(self, thread_id: str) -> Agent:
        agent = self._agents.get(thread_id)
        if agent is None:
            hooks: list[HookProvider | HookCallback[Any]] = [StepLimitHook(self._max_steps)]
            if self._risky:
                hooks.insert(0, ApprovalHook(self._risky))
            agent = Agent(
                model=self._model,
                tools=[_to_strands(tool) for tool in self._tools],
                system_prompt=self._system_prompt,
                hooks=hooks,
                callback_handler=None,
            )
            self._agents[thread_id] = agent
        return agent

    def _outcome(self, result: Any, thread_id: str) -> LoopOutcome:
        usage = self._usage(result, thread_id)
        if getattr(result, "stop_reason", "") == "interrupt" and result.interrupts:
            interrupt = result.interrupts[0]
            self._pending[thread_id] = interrupt.id
            reason = interrupt.reason if isinstance(interrupt.reason, Mapping) else {}
            arguments = reason.get("arguments")
            return LoopOutcome(
                status="interrupted",
                text="",
                tool=str(reason.get("tool")) if reason.get("tool") else None,
                arguments=arguments if isinstance(arguments, Mapping) else {},
                usage=usage,
            )
        agent = self._agents[thread_id]
        return LoopOutcome(
            status="completed", text=str(result).strip(), tools_called=_tools_called(agent.messages), usage=usage
        )

    def _usage(self, result: Any, thread_id: str) -> LoopUsage:
        """This turn's share of the agent's running totals (``EventLoopMetrics`` accumulate per agent)."""
        metrics = getattr(result, "metrics", None)
        totals = getattr(metrics, "accumulated_usage", None) or {}
        now = (
            int(getattr(metrics, "cycle_count", 0) or 0),
            int(totals.get("inputTokens", 0) or 0),
            int(totals.get("outputTokens", 0) or 0),
        )
        before = self._seen.get(thread_id, (0, 0, 0))
        self._seen[thread_id] = now
        config = self._model.get_config() if hasattr(self._model, "get_config") else {}
        model = str(config.get("model_id", "")) if isinstance(config, Mapping) else ""
        return LoopUsage(
            model_calls=max(0, now[0] - before[0]),
            input_tokens=max(0, now[1] - before[1]),
            output_tokens=max(0, now[2] - before[2]),
            model=model,
        )


def _tools_called(messages: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    names: list[str] = []
    for message in messages:
        for block in message.get("content", []):
            use = block.get("toolUse") if isinstance(block, Mapping) else None
            if isinstance(use, Mapping) and isinstance(use.get("name"), str):
                names.append(use["name"])
    return tuple(names)


def _to_strands(tool: ToolSpec) -> PythonAgentTool:
    def run(tool_use: Mapping[str, Any], **_state: Any) -> dict[str, Any]:
        result = tool.handler(dict(tool_use.get("input") or {}))
        text = result if isinstance(result, str) else json.dumps(result, sort_keys=True, default=str)
        return {"toolUseId": tool_use["toolUseId"], "status": "success", "content": [{"text": text}]}

    spec = {"name": tool.name, "description": tool.description, "inputSchema": {"json": dict(tool.input_schema)}}
    return PythonAgentTool(tool.name, spec, run)  # type: ignore[arg-type]


class ScriptedStrandsModel(Model):
    """Strands face of ``Script``. Offline only."""

    def __init__(self, script: Script) -> None:
        self.script = script
        self._config: dict[str, Any] = {"model_id": "agentcore-scripted"}

    def update_config(self, **model_config: Any) -> None:
        self._config.update(model_config)

    def get_config(self) -> dict[str, Any]:
        return dict(self._config)

    async def structured_output(self, output_model: Any, prompt: Any, system_prompt: str | None = None, **kwargs: Any):  # type: ignore[no-untyped-def]
        raise NotImplementedError("the scripted model has no structured output")
        yield {}  # pragma: no cover

    async def stream(  # type: ignore[override]
        self,
        messages: list[Any],
        tool_specs: list[Any] | None = None,
        system_prompt: str | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        yield {"messageStart": {"role": "assistant"}}
        user_index = max(
            (i for i, m in enumerate(messages) if m["role"] == "user" and any("text" in b for b in m["content"])),
            default=-1,
        )
        tail = messages[user_index + 1 :]
        result = _last_tool_result(tail)
        if result is not None:
            name, text = result
            for event in _text_events(self.script.answer(name, text)):
                yield event
            return
        user_text = "".join(b.get("text", "") for b in messages[user_index]["content"]) if user_index >= 0 else ""
        tool, args, reply = self.script.first_reply(user_text)
        if tool is None:
            for event in _text_events(reply):
                yield event
            return
        yield {"contentBlockStart": {"start": {"toolUse": {"toolUseId": f"call-{len(messages)}", "name": tool}}}}
        yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(args)}}}}
        yield {"contentBlockStop": {}}
        yield {"messageStop": {"stopReason": "tool_use"}}


def _text_events(text: str) -> list[dict[str, Any]]:
    return [
        {"contentBlockDelta": {"delta": {"text": text}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": "end_turn"}},
    ]


def _last_tool_result(messages: Sequence[Mapping[str, Any]]) -> tuple[str, str] | None:
    names: dict[str, str] = {}
    found: tuple[str, str] | None = None
    for message in messages:
        for block in message.get("content", []):
            use = block.get("toolUse")
            if isinstance(use, Mapping):
                names[str(use.get("toolUseId"))] = str(use.get("name"))
            outcome = block.get("toolResult")
            if isinstance(outcome, Mapping):
                text = "".join(part.get("text", "") for part in outcome.get("content", []) if isinstance(part, Mapping))
                if outcome.get("status") == "error":
                    text = f"rejected: {text}"
                found = (names.get(str(outcome.get("toolUseId")), "tool"), text)
    return found

"""``build_agent(config)``: one session API over three loops.

The order inside a turn follows docs/design/library.md "How a turn is built":
guard the user text, tag it as untrusted, run the loop, pause on a risky tool,
guard the text the user will see, then write memory through the memory client.
The front door has already checked identity, the session binding, quotas, and
the kill switch before ``run`` is called.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from agentcore_approvals import ApprovalError
from agentcore_guardrails import Blocked, Guard
from agentcore_memory import MemoryClient, MemoryWriteDenied
from agentcore_tools.idempotency import args_hash
from agentcore_tracing import TurnLog, emit_turn_log, turn_span

from agentcore_agent.approvals import ApprovalStore, InMemoryApprovalStore, PauseRequest, PauseTicket, utc_now
from agentcore_agent.config import PatternConfig
from agentcore_agent.frameworks.base import Loop, LoopOutcome, LoopUsage, ToolSpec, UnsupportedFramework
from agentcore_agent.scripted import Script
from agentcore_agent.untrusted import wrap

ATTR_RELEASE_ID = "agentcore.release_id"
ATTR_PATTERN = "agentcore.pattern"
BLOCKED_REPLY = "I can't help with that request."
WITHHELD_REPLY = "I can't share that answer."
UNRELEASED = "unreleased"


@dataclass(frozen=True)
class TurnResult:
    """``completed``, ``paused`` (``ticket`` set), or ``blocked`` by the guard."""

    status: str
    text: str
    session_id: str
    release_id: str
    ticket: PauseTicket | None = None
    tools_called: tuple[str, ...] = ()
    blocked_reason: str | None = None
    usage: LoopUsage | None = None


@dataclass(frozen=True)
class _Turn:
    session_id: str
    actor_id: str
    token_id: str | None = None


_CURRENT: ContextVar[_Turn | None] = ContextVar("agentcore_agent_turn", default=None)


class AgentSession:
    """What ``build_agent`` returns: ``run``, ``stream``, ``pause_for_human``, and ``resume``."""

    def __init__(
        self,
        *,
        config: PatternConfig,
        loop: Loop,
        tools: Sequence[ToolSpec],
        guard: Guard,
        approvals: ApprovalStore,
        memory: MemoryClient | None,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.config = config
        self.loop = loop
        self.tools = {tool.name: tool for tool in tools}
        self.guard = guard
        self.approvals = approvals
        self.memory = memory
        self._clock = clock
        self._min_session = int(config.section("lifecycle")["session_id_min"])
        self._paused: dict[str, PauseTicket] = {}

    @property
    def framework(self) -> str:
        return self.loop.framework

    @property
    def release_id(self) -> str:
        return self.config.release_id or UNRELEASED

    def run(self, prompt: str, *, session_id: str, actor_id: str) -> TurnResult:
        self._check_session(session_id, actor_id)
        started = time.perf_counter()
        error_class: str | None = None
        result: TurnResult | None = None
        try:
            with self._span(session_id):
                screened = self.guard.apply_input(prompt)
                if isinstance(screened, Blocked):
                    result = self._blocked(session_id, screened.reason, BLOCKED_REPLY)
                    return result
                token = _CURRENT.set(_Turn(session_id, actor_id))
                try:
                    outcome = self.loop.invoke(self._prompt(screened.text, actor_id), thread_id=session_id)
                finally:
                    _CURRENT.reset(token)
                result = self._finish(outcome, session_id=session_id, actor_id=actor_id, user_text=screened.text)
                return result
        except Exception as exc:
            error_class = type(exc).__name__
            raise
        finally:
            self._log(session_id, actor_id, started, error_class, result)

    def stream(self, prompt: str, *, session_id: str, actor_id: str) -> Iterator[str]:
        """Yield guarded chunks. A blocked chunk ends the stream with the withheld reply."""
        self._check_session(session_id, actor_id)
        screened = self.guard.apply_input(prompt)
        if isinstance(screened, Blocked):
            yield BLOCKED_REPLY
            return
        token = _CURRENT.set(_Turn(session_id, actor_id))
        try:
            for chunk in self.loop.stream(self._prompt(screened.text, actor_id), thread_id=session_id):
                shown = self.guard.apply_output(chunk)
                if isinstance(shown, Blocked):
                    yield WITHHELD_REPLY
                    return
                yield shown.text
        finally:
            _CURRENT.reset(token)

    def pause_for_human(self, request: PauseRequest) -> PauseTicket:
        """Open an approval for ``request``. The waiting state belongs on the job row, not the session."""
        ticket = self.approvals.open(request, now=self._clock())
        self._paused[request.session_id] = ticket
        return ticket

    def resume(self, *, session_id: str, actor_id: str, token_id: str, approved: bool, message: str = "") -> TurnResult:
        """Continue a paused turn after a reviewer decided. The handler spends the token."""
        self._check_session(session_id, actor_id)
        ticket = self.approvals.get(token_id)
        if ticket.actor_id != actor_id:
            raise ApprovalError("mismatch")
        started = time.perf_counter()
        error_class: str | None = None
        result: TurnResult | None = None
        try:
            with self._span(session_id):
                token = _CURRENT.set(_Turn(session_id, actor_id, token_id if approved else None))
                try:
                    outcome = self.loop.resume(
                        approved=approved,
                        message=message or "rejected by reviewer",
                        thread_id=session_id,
                    )
                finally:
                    _CURRENT.reset(token)
                self._paused.pop(session_id, None)
                result = self._finish(outcome, session_id=session_id, actor_id=actor_id, user_text="")
                return result
        except Exception as exc:
            error_class = type(exc).__name__
            raise
        finally:
            self._log(session_id, actor_id, started, error_class, result)

    def _finish(self, outcome: LoopOutcome, *, session_id: str, actor_id: str, user_text: str) -> TurnResult:
        if outcome.status == "interrupted" and outcome.tool is not None:
            spec = self.tools.get(outcome.tool)
            approval = self.config.section("approval")
            ticket = self.pause_for_human(
                PauseRequest(
                    tool=outcome.tool,
                    arguments=dict(outcome.arguments),
                    actor_id=actor_id,
                    action=spec.action if spec is not None else "change",
                    session_id=session_id,
                    reviewers=int(approval["reviewers"]),
                    expire_s=int(approval["expire_s"]),
                    summary=spec.description if spec is not None else outcome.tool,
                )
            )
            return TurnResult(
                status="paused",
                text="",
                session_id=session_id,
                release_id=self.release_id,
                ticket=ticket,
                tools_called=outcome.tools_called,
                usage=outcome.usage,
            )
        shown = self.guard.apply_output(outcome.text)
        if isinstance(shown, Blocked):
            return replace(
                self._blocked(session_id, shown.reason, WITHHELD_REPLY, outcome.tools_called), usage=outcome.usage
            )
        self._remember(session_id, actor_id, user_text, shown.text)
        return TurnResult(
            status="completed",
            text=shown.text,
            session_id=session_id,
            release_id=self.release_id,
            tools_called=outcome.tools_called,
            usage=outcome.usage,
        )

    def _prompt(self, user_text: str, actor_id: str) -> str:
        parts: list[str] = []
        if self.memory is not None:
            for hit in self.memory.retrieve(actor_id, user_text):
                parts.append(wrap("document", hit.event.content))
        parts.append(wrap("user", user_text))
        return "\n".join(parts)

    def _remember(self, session_id: str, actor_id: str, user_text: str, reply: str) -> None:
        if self.memory is None:
            return
        for role, content in (("user", user_text), ("assistant", reply)):
            if not content:
                continue
            try:
                self.memory.create_event(session_id=session_id, actor_id=actor_id, role=role, content=content)
            except MemoryWriteDenied:
                continue

    def _blocked(self, session_id: str, reason: str, reply: str, tools_called: tuple[str, ...] = ()) -> TurnResult:
        return TurnResult(
            status="blocked",
            text=reply,
            session_id=session_id,
            release_id=self.release_id,
            tools_called=tools_called,
            blocked_reason=reason,
        )

    def _check_session(self, session_id: str, actor_id: str) -> None:
        if len(session_id) < self._min_session:
            raise ValueError(f"session id must be at least {self._min_session} characters")
        if not actor_id.strip():
            raise ValueError("actor id is required")

    @contextmanager
    def _span(self, session_id: str) -> Iterator[Any]:
        with turn_span(agent_version=self.release_id, session_id=session_id) as span:
            span.set_attribute(ATTR_RELEASE_ID, self.release_id)
            span.set_attribute(ATTR_PATTERN, self.config.name)
            yield span

    def _log(
        self, session_id: str, actor_id: str, started: float, error_class: str | None, result: TurnResult | None
    ) -> None:
        tool = result.tools_called[-1] if result is not None and result.tools_called else None
        emit_turn_log(
            TurnLog(
                runtime_session_id=session_id,
                actor_id=actor_id,
                agent_version=self.release_id,
                request_id=str(uuid.uuid4()),
                latency_ms=(time.perf_counter() - started) * 1000,
                tool_name=tool,
                error_class=error_class,
            )
        )


def build_agent(
    config: PatternConfig,
    *,
    tools: Sequence[ToolSpec] = (),
    model: Any | None = None,
    script: Script | None = None,
    guard: Guard | None = None,
    approvals: ApprovalStore | None = None,
    memory: MemoryClient | None = None,
    environment: str = "dev",
    harness_client: Any | None = None,
    harness_arn: str = "",
    checkpointer: Any | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> AgentSession:
    """Build the session for ``config.framework``.

    Pass ``model`` (a LangChain chat model or a Strands model) for a real
    loop, or ``script`` for the offline scripted model. ``harness`` needs
    ``harness_client`` and ``harness_arn`` instead.
    """
    _check_tools(config, tools)
    approvals = approvals if approvals is not None else InMemoryApprovalStore()
    guard = guard if guard is not None else Guard()
    wrapped = tuple(_spend_token_first(tool, approvals, clock) if tool.risky else tool for tool in tools)
    if memory is None and bool(config.section("memory")["enabled"]):
        memory = MemoryClient(guard, agent_version=config.release_id or UNRELEASED, environment=environment)
    lifecycle = config.section("lifecycle")
    max_steps = int(lifecycle["max_steps"])
    framework = config.framework
    loop: Loop
    if framework == "harness":
        from agentcore_agent.frameworks.harness_loop import HarnessLoop

        if harness_client is None:
            raise UnsupportedFramework("framework harness needs a bedrock-agentcore client")
        loop = HarnessLoop(
            client=harness_client,
            harness_arn=harness_arn,
            tools=wrapped,
            max_steps=max_steps,
            timeout_s=int(lifecycle["timeout_s"]),
        )
    elif framework == "strands":
        from agentcore_agent.frameworks.strands_loop import ScriptedStrandsModel, StrandsLoop

        chosen = model if model is not None else ScriptedStrandsModel(_need_script(script))
        loop = StrandsLoop(model=chosen, tools=wrapped, system_prompt=config.system_prompt(), max_steps=max_steps)
    elif framework == "create_agent":
        from agentcore_agent.frameworks.langchain_loop import LangChainLoop, ScriptedChatModel

        chosen = model if model is not None else ScriptedChatModel(script=_need_script(script))
        loop = LangChainLoop(
            model=chosen,
            tools=wrapped,
            system_prompt=config.system_prompt(),
            max_steps=max_steps,
            checkpointer=checkpointer,
        )
    else:
        raise UnsupportedFramework(f"unknown framework {framework!r}")
    return AgentSession(
        config=config,
        loop=loop,
        tools=wrapped,
        guard=guard,
        approvals=approvals,
        memory=memory,
        clock=clock,
    )


def _check_tools(config: PatternConfig, tools: Sequence[ToolSpec]) -> None:
    listed = set(config.tools)
    unknown = sorted(tool.name for tool in tools if tool.name not in listed)
    if unknown:
        raise UnsupportedFramework(f"tools not in tools.from_registry: {unknown}")
    required = config.approval_required_for
    unguarded = sorted(tool.name for tool in tools if tool.action in required and not tool.risky)
    if unguarded:
        raise UnsupportedFramework(f"tools whose action needs approval are marked read: {unguarded}")
    mislabelled = sorted(tool.name for tool in tools if tool.risky and tool.action not in required)
    if mislabelled:
        raise UnsupportedFramework(f"approval.required_for does not list the action of: {mislabelled}")


def _need_script(script: Script | None) -> Script:
    if script is None:
        raise UnsupportedFramework("pass model= for a real loop or script= for the offline scripted model")
    return script


def _spend_token_first(tool: ToolSpec, approvals: ApprovalStore, clock: Callable[[], datetime]) -> ToolSpec:
    """A risky handler runs only after spending an approved token bound to this call."""
    inner = tool.handler

    def handler(arguments: Mapping[str, Any]) -> Any:
        turn = _CURRENT.get()
        if turn is None or turn.token_id is None:
            return f"rejected: {tool.name} needs an approved token"
        try:
            approvals.consume(
                turn.token_id,
                tool=tool.name,
                args_hash=args_hash(dict(arguments)),
                actor_id=turn.actor_id,
                now=clock(),
            )
        except ApprovalError as exc:
            return f"rejected: approval {exc.code}"
        return inner(arguments)

    return replace(tool, handler=handler)

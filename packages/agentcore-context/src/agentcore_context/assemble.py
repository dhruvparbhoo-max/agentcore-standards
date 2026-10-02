"""Build the prompt for one turn under a token budget.

Token counts use the length heuristic (characters // 4). That is not model
usage and not a USD estimate. System text, the state bar, and the current user
turn are not dropped. Tool results go first, then older memory, then the
lowest-ranked retrievals.
"""

from __future__ import annotations

from collections.abc import Sequence

from agentcore_context.state_bar import StateBar


class ContextBudgetError(Exception):
    """System, state bar, and the user turn do not fit in the budget."""


class ScreenedLine:
    """One memory line that has already passed the guard. Unscreened lines cannot be built."""

    def __init__(self, *, role: str, content: str, screened: bool) -> None:
        if screened is not True:
            raise ValueError("memory line was not screened")
        if role not in {"user", "assistant", "tool"}:
            raise ValueError("invalid role")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("content is required")
        self.role = role
        self.content = content
        self.screened = True


class AssembledContext:
    """The prompt and what was left out."""

    def __init__(self, *, text: str, omissions: tuple[str, ...], token_estimate: int) -> None:
        self.text = text
        self.omissions = omissions
        self.token_estimate = token_estimate
        self.estimate_source = "length-heuristic"

    def as_system_prompt(self) -> str:
        """Return the assembled text for a system prompt slot."""
        return self.text


def assemble_context(
    *,
    system: str,
    user: str,
    state_bar: StateBar | None = None,
    retrievals: Sequence[str] = (),
    tool_results: Sequence[str] = (),
    memory: Sequence[ScreenedLine] = (),
    budget_tokens: int = 2_000,
) -> AssembledContext:
    """Assemble one turn. ``memory`` must already be screened lines."""
    if not isinstance(system, str) or not system.strip():
        raise ValueError("system text is required")
    if not isinstance(user, str) or not user.strip():
        raise ValueError("user text is required")
    if isinstance(budget_tokens, bool) or not isinstance(budget_tokens, int) or budget_tokens < 32:
        raise ValueError("budget_tokens must be at least 32")
    bar = "" if state_bar is None else state_bar.render()
    pinned = _section("system", system.strip())
    if bar:
        pinned += "\n" + _section("state", bar)
    pinned += "\n" + _section("user", user.strip())
    if _tokens(pinned) > budget_tokens:
        raise ContextBudgetError("pinned context exceeds the budget")
    retrieval_blocks = [_section("retrieval", item) for item in retrievals if item.strip()]
    tool_blocks = [_section("tool", item) for item in tool_results if item.strip()]
    memory_blocks = [_section("memory", f"{line.role}: {line.content}") for line in memory]
    kept_retrievals = list(retrieval_blocks)
    kept_tools = list(tool_blocks)
    kept_memory = list(memory_blocks)
    omissions: list[str] = []
    while _tokens(_join(pinned, kept_retrievals, kept_memory, kept_tools)) > budget_tokens:
        if kept_tools:
            kept_tools.pop(0)
            omissions.append("tool")
            continue
        if kept_memory:
            kept_memory.pop(0)
            omissions.append("memory")
            continue
        if kept_retrievals:
            kept_retrievals.pop()
            omissions.append("retrieval")
            continue
        break
    text = _join(pinned, kept_retrievals, kept_memory, kept_tools)
    return AssembledContext(text=text, omissions=tuple(omissions), token_estimate=_tokens(text))


def line_from_screened(*, role: str, content: str, screened: bool) -> ScreenedLine:
    """Build a memory line. ``screened`` must be true."""
    return ScreenedLine(role=role, content=content, screened=screened)


def _section(name: str, body: str) -> str:
    return f"[{name}]\n{body.strip()}"


def _join(pinned: str, retrievals: list[str], memory: list[str], tools: list[str]) -> str:
    parts = [pinned, *retrievals, *memory, *tools]
    return "\n".join(part for part in parts if part)


def _tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, len(text) // 4)

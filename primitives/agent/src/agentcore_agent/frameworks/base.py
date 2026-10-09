"""What every loop shares: the tool shape, the outcome shape, and the loop protocol."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

READ = "read"
ToolHandler = Callable[[Mapping[str, Any]], Any]


@dataclass(frozen=True)
class ToolSpec:
    """One tool a loop may call. ``action`` is ``read`` or one of send, spend, delete, change."""

    name: str
    description: str
    input_schema: Mapping[str, Any]
    handler: ToolHandler
    action: str = READ

    @property
    def risky(self) -> bool:
        return self.action != READ


@dataclass(frozen=True)
class LoopUsage:
    """Model calls and tokens for one turn, as the framework reported them. The front door prices this."""

    model_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_calls": self.model_calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "model": self.model,
        }


@dataclass(frozen=True)
class LoopOutcome:
    """``completed`` with text, or ``interrupted`` on a risky tool with its arguments."""

    status: str
    text: str
    tool: str | None = None
    arguments: Mapping[str, Any] = field(default_factory=dict)
    tools_called: tuple[str, ...] = ()
    usage: LoopUsage | None = None


class Loop(Protocol):
    framework: str

    def invoke(self, prompt: str, *, thread_id: str) -> LoopOutcome:
        """Run one turn until it answers or pauses on a risky tool."""

    def resume(self, *, approved: bool, message: str, thread_id: str) -> LoopOutcome:
        """Continue a paused turn after a person decided."""

    def stream(self, prompt: str, *, thread_id: str) -> Iterator[str]:
        """Yield text chunks for one turn. A pause ends the stream."""


class UnsupportedFramework(ValueError):
    """The framework cannot honour this pattern's config."""


def risky_reviews(tools: list[ToolSpec] | tuple[ToolSpec, ...]) -> dict[str, str]:
    """Tool name to the sentence a reviewer sees, for tools that need approval."""
    return {tool.name: f"{tool.action}: {tool.description}" for tool in tools if tool.risky}

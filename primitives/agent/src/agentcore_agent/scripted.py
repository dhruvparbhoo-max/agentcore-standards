"""A scripted model for offline tests, ``make local``, and the in-process judge.

It is not a model. It follows rules: a regex on the last user text picks a tool
and its arguments, then the answer quotes the tool result. The same script runs
under LangChain and Strands, so the framework switch is covered without a
model credential. A hosted deploy never selects it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from agentcore_agent.untrusted import unwrap_last

ArgsFrom = Callable[[re.Match[str]], dict[str, Any]]


@dataclass(frozen=True)
class ScriptRule:
    pattern: str
    tool: str | None = None
    arguments: ArgsFrom | Mapping[str, Any] | None = None
    reply: str = ""

    def match(self, text: str) -> re.Match[str] | None:
        return re.search(self.pattern, text, flags=re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class Script:
    rules: Sequence[ScriptRule]
    fallback: str = "I can only help with the tasks this agent was built for."

    def plan(self, user_text: str) -> tuple[ScriptRule, dict[str, Any]] | None:
        for rule in self.rules:
            found = rule.match(user_text)
            if found is None:
                continue
            args = rule.arguments(found) if callable(rule.arguments) else dict(rule.arguments or {})
            return rule, args
        return None

    def first_reply(self, user_text: str) -> tuple[str | None, dict[str, Any], str]:
        """The tool to call (or ``None``), its arguments, and the reply when no tool runs."""
        user_text = unwrap_last(user_text)
        planned = self.plan(user_text)
        if planned is None:
            return None, {}, self.fallback
        rule, args = planned
        if rule.tool is None:
            return None, {}, rule.reply.format(**_groups(rule, user_text))
        return rule.tool, args, ""

    def answer(self, tool: str, result: str) -> str:
        lowered = result.lower()
        refusals = ("was rejected", "not approved", "rejected the tool call")
        if lowered.startswith("rejected") or any(phrase in lowered for phrase in refusals):
            return f"rejected:{tool}"
        return f"{tool}: {result}"


def _groups(rule: ScriptRule, text: str) -> dict[str, str]:
    found = rule.match(text)
    if found is None:
        return {}
    return {key: value for key, value in found.groupdict().items() if value is not None}


def echo_script() -> Script:
    """The template agent's offline behaviour: answer ``pong:<text>`` with no tool."""
    return Script(rules=(ScriptRule(pattern=r"(?P<text>\S.*)", reply="pong:{text}"),))

"""Shorten a tool result before it re-enters the prompt.

The head and the tail are kept. The middle is replaced with an omitted count.
A short result is returned unchanged. Arguments are not added.
"""

from __future__ import annotations


class CompactedToolOutput:
    """A tool payload that fits a character budget."""

    def __init__(
        self,
        *,
        tool_name: str,
        text: str,
        truncated: bool,
        original_chars: int,
        kept_chars: int,
    ) -> None:
        self.tool_name = tool_name
        self.text = text
        self.truncated = truncated
        self.original_chars = original_chars
        self.kept_chars = kept_chars


def compact_tool_output(text: str, *, tool_name: str, max_chars: int = 2_000) -> CompactedToolOutput:
    """Keep the start and the end of ``text`` when it is longer than ``max_chars``."""
    if not isinstance(tool_name, str) or not tool_name.strip():
        raise ValueError("tool_name is required")
    if not isinstance(text, str):
        raise ValueError("text is required")
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 64:
        raise ValueError("max_chars must be at least 64")
    original = len(text)
    if original <= max_chars:
        return CompactedToolOutput(
            tool_name=tool_name,
            text=text,
            truncated=False,
            original_chars=original,
            kept_chars=original,
        )
    marker_budget = 48
    body_budget = max(2, max_chars - marker_budget)
    head_len = max(1, (body_budget * 6) // 10)
    tail_len = max(1, body_budget - head_len)
    omitted = max(0, original - head_len - tail_len)
    marker = f"\n[truncated omitted={omitted}]\n"
    while head_len + tail_len + len(marker) > max_chars and (head_len > 1 or tail_len > 1):
        if head_len >= tail_len and head_len > 1:
            head_len -= 1
        elif tail_len > 1:
            tail_len -= 1
        omitted = max(0, original - head_len - tail_len)
        marker = f"\n[truncated omitted={omitted}]\n"
    compacted = text[:head_len] + marker + text[-tail_len:]
    return CompactedToolOutput(
        tool_name=tool_name,
        text=compacted,
        truncated=True,
        original_chars=original,
        kept_chars=len(compacted),
    )

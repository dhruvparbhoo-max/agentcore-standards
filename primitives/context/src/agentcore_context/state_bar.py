"""A short status line: open work, tool counts, and the circuit state.

The bar is injected ahead of retrieved text so a full tool transcript cannot
push the counts out of the window. Rendering never includes tool arguments.
"""

from __future__ import annotations

_CIRCUITS = frozenset({"closed", "open", "half_open"})


class StateBar:
    """Counts and open todos for one turn."""

    def __init__(
        self,
        *,
        open_todos: tuple[str, ...] = (),
        tool_calls: int = 0,
        tool_errors: int = 0,
        circuit: str = "closed",
    ) -> None:
        if circuit not in _CIRCUITS:
            raise ValueError("invalid circuit state")
        self.open_todos = tuple(_todo(item) for item in open_todos)
        self.tool_calls = _count(tool_calls, "tool_calls")
        self.tool_errors = _count(tool_errors, "tool_errors")
        self.circuit = circuit

    def render(self, *, max_chars: int = 400) -> str:
        """Render the bar. Extra todos become an omitted count, not a silent drop of the totals."""
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 80:
            raise ValueError("max_chars must be at least 80")
        header = (
            f"[state] todos={len(self.open_todos)} tools={self.tool_calls} "
            f"errors={self.tool_errors} circuit={self.circuit}"
        )
        lines = [header]
        used = len(header)
        shown = 0
        for todo in self.open_todos:
            line = f"\n- {todo}"
            if used + len(line) > max_chars:
                break
            lines.append(line)
            used += len(line)
            shown += 1
        omitted = len(self.open_todos) - shown
        if omitted:
            suffix = f"\n- [omitted todos={omitted}]"
            if used + len(suffix) <= max_chars:
                lines.append(suffix)
            else:
                lines = [header, suffix.strip()]
        return "".join(lines)


def _count(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be >= 0")
    return value


def _todo(value: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 120:
        raise ValueError("invalid todo")
    if any(ord(char) < 32 for char in value):
        raise ValueError("invalid todo")
    return value.strip()

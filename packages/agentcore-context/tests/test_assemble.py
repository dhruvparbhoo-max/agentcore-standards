"""Pinned state bar, screened memory only, and tool results dropped first."""

import pytest
from agentcore_context import AssembledContext, ContextBudgetError, StateBar, assemble_context, line_from_screened


def test_unscreened_memory_cannot_be_assembled() -> None:
    with pytest.raises(ValueError, match="screened"):
        line_from_screened(role="user", content="secret note", screened=False)


def test_state_bar_survives_when_tool_results_are_dropped() -> None:
    bar = StateBar(open_todos=("file the invoice",), tool_calls=4, tool_errors=1, circuit="open")
    assembled = assemble_context(
        system="You answer from citations.",
        user="Where is invoice 42?",
        state_bar=bar,
        tool_results=("x" * 4000,),
        memory=(line_from_screened(role="assistant", content="earlier note " * 80, screened=True),),
        budget_tokens=80,
    )
    assert isinstance(assembled, AssembledContext)
    assert "[state]" in assembled.text
    assert "tools=4" in assembled.text
    assert "errors=1" in assembled.text
    assert "circuit=open" in assembled.text
    assert "tool" in assembled.omissions
    assert assembled.estimate_source == "length-heuristic"
    assert "Where is invoice 42?" in assembled.text


def test_pinned_context_that_exceeds_the_budget_raises() -> None:
    with pytest.raises(ContextBudgetError):
        assemble_context(system="s" * 2000, user="u" * 2000, budget_tokens=32)


def test_state_bar_keeps_counts_when_todos_are_truncated() -> None:
    todos = tuple(f"todo number {index:02d} with extra words" for index in range(20))
    rendered = StateBar(open_todos=todos, tool_calls=2, tool_errors=0).render(max_chars=120)
    assert rendered.startswith("[state] todos=20 tools=2 errors=0 circuit=closed")
    assert "omitted todos=" in rendered

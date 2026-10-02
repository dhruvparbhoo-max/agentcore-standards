"""One recovery loop around a registry call.

The clock does not sleep. A retryable result may run twice. A fatal result
is returned as-is. The circuit is process-local and resets with the desk.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agentcore_recovery import AttemptOutcome, CircuitBreaker, Clock, RecoveryBudget, run_with_recovery
from agentcore_tools import ErrorClass, ToolRegistry, ToolResult

_circuit = CircuitBreaker(failure_threshold=4, cooldown_ms=30_000)
_clock = Clock()
_budget = RecoveryBudget(
    max_attempts=2,
    max_elapsed_ms=10_000,
    base_delay_ms=1,
    max_delay_ms=1,
)


def reset_recovery() -> None:
    """Start a fresh circuit so one test cannot open it for the next."""
    global _circuit, _clock
    _circuit = CircuitBreaker(failure_threshold=4, cooldown_ms=30_000)
    _clock = Clock()


def invoke_with_recovery(
    registry: ToolRegistry,
    name: str,
    args: Mapping[str, Any],
    **kwargs: Any,
) -> ToolResult:
    """Call ``invoke_tool`` under the shelf recovery budget."""
    held: dict[str, ToolResult] = {}

    def operation() -> AttemptOutcome:
        result = registry.invoke_tool(name, dict(args), **kwargs)
        held["result"] = result
        error = result.error
        if error is not None and error.error_class is ErrorClass.RETRYABLE:
            return AttemptOutcome(ok=False, retryable=True, code=error.code)
        code = "ok" if error is None else error.code
        return AttemptOutcome(ok=error is None, retryable=False, code=code)

    run_with_recovery(
        operation,
        budget=_budget,
        circuit=_circuit,
        clock=_clock,
        jitter=lambda _span, _attempt: 0,
    )
    result = held.get("result")
    if result is None:
        raise RuntimeError("recovery did not call the tool")
    return result

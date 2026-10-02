"""Retry the retryable path, stop on fatal, and refuse a retry storm."""

from agentcore_recovery import (
    AttemptOutcome,
    CircuitBreaker,
    Clock,
    InFlightGate,
    RecoveryBudget,
    run_with_recovery,
)


def _budget() -> RecoveryBudget:
    return RecoveryBudget(max_attempts=4, max_elapsed_ms=1_000, base_delay_ms=10, max_delay_ms=40)


def _half(span_ms: int, _attempt: int) -> int:
    return span_ms // 2


def test_retryable_failure_then_success_sleeps_once() -> None:
    calls = {"n": 0}

    def operation() -> AttemptOutcome:
        calls["n"] += 1
        if calls["n"] == 1:
            return AttemptOutcome(ok=False, retryable=True, code="timeout")
        return AttemptOutcome(ok=True, retryable=False, code="ok")

    clock = Clock()
    result = run_with_recovery(
        operation,
        budget=_budget(),
        circuit=CircuitBreaker(failure_threshold=5, cooldown_ms=100),
        clock=clock,
        jitter=_half,
    )
    assert result.ok
    assert result.attempts == 2
    assert result.stop_reason == ""
    assert clock.now_ms > 0


def test_fatal_is_not_retried_and_does_not_open_the_circuit() -> None:
    calls = {"n": 0}
    circuit = CircuitBreaker(failure_threshold=1, cooldown_ms=100)

    def operation() -> AttemptOutcome:
        calls["n"] += 1
        return AttemptOutcome(ok=False, retryable=False, code="schema_rejected")

    result = run_with_recovery(
        operation,
        budget=_budget(),
        circuit=circuit,
        clock=Clock(),
        jitter=_half,
    )
    assert result.stop_reason == "fatal"
    assert calls["n"] == 1
    assert circuit.state.value == "closed"


def test_circuit_opens_and_the_next_run_does_not_call() -> None:
    calls = {"n": 0}
    circuit = CircuitBreaker(failure_threshold=2, cooldown_ms=10_000)

    def operation() -> AttemptOutcome:
        calls["n"] += 1
        return AttemptOutcome(ok=False, retryable=True, code="timeout")

    first = run_with_recovery(
        operation,
        budget=_budget(),
        circuit=circuit,
        clock=Clock(),
        jitter=_half,
    )
    assert first.stop_reason == "circuit_open"
    before = calls["n"]
    second = run_with_recovery(
        operation,
        budget=_budget(),
        circuit=circuit,
        clock=Clock(),
        jitter=_half,
    )
    assert second.stop_reason == "circuit_open"
    assert second.attempts == 0
    assert calls["n"] == before


def test_in_flight_cap_does_not_start_another_loop() -> None:
    calls = {"n": 0}
    gate = InFlightGate(1)
    assert gate.acquire()

    def operation() -> AttemptOutcome:
        calls["n"] += 1
        return AttemptOutcome(ok=True, retryable=False, code="ok")

    result = run_with_recovery(
        operation,
        budget=_budget(),
        circuit=CircuitBreaker(failure_threshold=3, cooldown_ms=10),
        clock=Clock(),
        gate=gate,
        jitter=_half,
    )
    assert result.stop_reason == "in_flight"
    assert calls["n"] == 0


def test_elapsed_budget_stops_before_sleeping_past_the_cap() -> None:
    def operation() -> AttemptOutcome:
        return AttemptOutcome(ok=False, retryable=True, code="timeout")

    clock = Clock()
    result = run_with_recovery(
        operation,
        budget=RecoveryBudget(max_attempts=5, max_elapsed_ms=1, base_delay_ms=50, max_delay_ms=50),
        circuit=CircuitBreaker(failure_threshold=10, cooldown_ms=10_000),
        clock=clock,
        jitter=lambda span_ms, _attempt: span_ms,
    )
    assert result.stop_reason == "budget_elapsed"
    assert clock.now_ms == 0

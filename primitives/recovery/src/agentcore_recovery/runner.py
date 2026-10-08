"""One recovery loop with a retry budget, a circuit, and an in-flight cap.

Backoff is capped exponential with full jitter. The jitter function is injected
so tests stay stable. The default draws uniformly from zero through the span.
A death spiral is the combination this runner refuses: unbounded attempts,
unbounded wait, and unbounded concurrent retries.
"""

from __future__ import annotations

import random
import threading
from collections.abc import Callable

from agentcore_recovery.circuit import CircuitBreaker


class AttemptOutcome:
    """What one call did. ``retryable`` is ignored when ``ok`` is true."""

    def __init__(self, *, ok: bool, retryable: bool, code: str) -> None:
        if not code:
            raise ValueError("code is required")
        self.ok = ok
        self.retryable = retryable
        self.code = code


class RecoveryBudget:
    """Caps for one logical operation, including its retries."""

    def __init__(
        self,
        *,
        max_attempts: int,
        max_elapsed_ms: int,
        base_delay_ms: int,
        max_delay_ms: int,
    ) -> None:
        self.max_attempts = _positive(max_attempts, "max_attempts")
        self.max_elapsed_ms = _positive(max_elapsed_ms, "max_elapsed_ms")
        self.base_delay_ms = _positive(base_delay_ms, "base_delay_ms")
        self.max_delay_ms = _positive(max_delay_ms, "max_delay_ms")

    def delay_span_ms(self, attempt: int) -> int:
        """Upper bound of the backoff after a failure at ``attempt`` (zero-based)."""
        if attempt < 0:
            raise ValueError("attempt must be >= 0")
        span = self.base_delay_ms
        for _ in range(attempt):
            if span >= self.max_delay_ms:
                return self.max_delay_ms
            span *= 2
        if span < self.max_delay_ms:
            return span
        return self.max_delay_ms


class InFlightGate:
    """How many recovery loops may run at once in this process."""

    def __init__(self, limit: int) -> None:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be >= 1")
        self._limit = limit
        self._current = 0
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        """Take a slot. False means the cap is already reached."""
        with self._lock:
            if self._current >= self._limit:
                return False
            self._current += 1
            return True

    def release(self) -> None:
        """Return a slot. Extra releases are ignored."""
        with self._lock:
            if self._current > 0:
                self._current -= 1


class Clock:
    """Monotonic milliseconds the runner sleeps on. Tests advance this without waiting."""

    def __init__(self, *, start_ms: int = 0) -> None:
        self.now_ms = start_ms

    def sleep(self, delay_ms: int) -> None:
        if delay_ms < 0:
            raise ValueError("delay_ms must be >= 0")
        self.now_ms += delay_ms


class RecoveryResult:
    """The last outcome and why the loop stopped. ``stop_reason`` is empty on success."""

    def __init__(self, *, ok: bool, attempts: int, stop_reason: str, code: str) -> None:
        self.ok = ok
        self.attempts = attempts
        self.stop_reason = stop_reason
        self.code = code


Jitter = Callable[[int, int], int]


def full_jitter(span_ms: int, _attempt: int) -> int:
    """Uniform draw from 0 through ``span_ms`` inclusive."""
    if span_ms <= 0:
        return 0
    return random.randint(0, span_ms)


def run_with_recovery(
    operation: Callable[[], AttemptOutcome],
    *,
    budget: RecoveryBudget,
    circuit: CircuitBreaker,
    clock: Clock,
    gate: InFlightGate | None = None,
    jitter: Jitter = full_jitter,
) -> RecoveryResult:
    """Call ``operation`` until it succeeds, a fatal result, or a cap."""
    inflight = gate if gate is not None else InFlightGate(1)
    if not inflight.acquire():
        return RecoveryResult(ok=False, attempts=0, stop_reason="in_flight", code="in_flight")
    try:
        return _loop(operation, budget=budget, circuit=circuit, clock=clock, jitter=jitter)
    finally:
        inflight.release()


def _loop(
    operation: Callable[[], AttemptOutcome],
    *,
    budget: RecoveryBudget,
    circuit: CircuitBreaker,
    clock: Clock,
    jitter: Jitter,
) -> RecoveryResult:
    started = clock.now_ms
    attempts = 0
    while True:
        if circuit.admit(clock.now_ms).value == "open":
            return RecoveryResult(ok=False, attempts=attempts, stop_reason="circuit_open", code="circuit_open")
        if attempts >= budget.max_attempts:
            return RecoveryResult(ok=False, attempts=attempts, stop_reason="budget_attempts", code="budget_attempts")
        outcome = operation()
        attempts += 1
        if outcome.ok:
            circuit.record_success()
            return RecoveryResult(ok=True, attempts=attempts, stop_reason="", code=outcome.code)
        if not outcome.retryable:
            return RecoveryResult(ok=False, attempts=attempts, stop_reason="fatal", code=outcome.code)
        circuit.record_failure(clock.now_ms)
        if attempts >= budget.max_attempts:
            return RecoveryResult(ok=False, attempts=attempts, stop_reason="budget_attempts", code=outcome.code)
        if circuit.state.value == "open":
            return RecoveryResult(ok=False, attempts=attempts, stop_reason="circuit_open", code=outcome.code)
        span = budget.delay_span_ms(attempts - 1)
        delay = jitter(span, attempts - 1)
        if delay < 0 or delay > span:
            raise ValueError("jitter must stay inside the span")
        elapsed_after = (clock.now_ms - started) + delay
        if elapsed_after > budget.max_elapsed_ms:
            return RecoveryResult(ok=False, attempts=attempts, stop_reason="budget_elapsed", code=outcome.code)
        clock.sleep(delay)


def _positive(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be >= 1")
    return value

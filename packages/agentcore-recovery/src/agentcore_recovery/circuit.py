"""Closed, open, and half-open. A half-open failure opens the circuit again."""

from __future__ import annotations

from enum import StrEnum


class CircuitState(StrEnum):
    """Whether a call may proceed."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Trip after consecutive retryable failures. Fatal outcomes are not recorded here."""

    def __init__(self, *, failure_threshold: int, cooldown_ms: int) -> None:
        if isinstance(failure_threshold, bool) or not isinstance(failure_threshold, int) or failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if isinstance(cooldown_ms, bool) or not isinstance(cooldown_ms, int) or cooldown_ms < 1:
            raise ValueError("cooldown_ms must be >= 1")
        self._threshold = failure_threshold
        self._cooldown_ms = cooldown_ms
        self._failures = 0
        self._opened_at: int | None = None
        self.state = CircuitState.CLOSED

    def admit(self, now_ms: int) -> CircuitState:
        """Return the state the caller must obey. ``OPEN`` means do not call."""
        _millis(now_ms)
        if (
            self.state is CircuitState.OPEN
            and self._opened_at is not None
            and now_ms - self._opened_at >= self._cooldown_ms
        ):
            self.state = CircuitState.HALF_OPEN
        return self.state

    def record_success(self) -> None:
        """Close the circuit after a successful probe or a normal success."""
        self._failures = 0
        self._opened_at = None
        self.state = CircuitState.CLOSED

    def record_failure(self, now_ms: int) -> None:
        """Count one retryable failure. Half-open failure opens immediately."""
        _millis(now_ms)
        if self.state is CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self._opened_at = now_ms
            return
        self._failures += 1
        if self._failures >= self._threshold:
            self.state = CircuitState.OPEN
            self._opened_at = now_ms


def _millis(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("now_ms must be >= 0")

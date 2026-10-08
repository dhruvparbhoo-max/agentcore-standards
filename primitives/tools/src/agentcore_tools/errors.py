"""Structured tool failures. Retryable errors carry a backoff hint. Fatal errors do not."""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Any


class ErrorClass(StrEnum):
    """Whether the caller may repeat the same tool call."""

    RETRYABLE = "retryable"
    FATAL = "fatal"


class ToolError:
    """Operational failure returned by ``invoke_tool``. It is not a raised exception."""

    def __init__(
        self,
        *,
        error_class: ErrorClass,
        code: str,
        message: str,
        backoff_ms: int | None,
    ) -> None:
        if not code or not message:
            raise ValueError("code and message are required")
        if error_class is ErrorClass.FATAL and backoff_ms is not None:
            raise ValueError("fatal errors have no backoff")
        if error_class is ErrorClass.RETRYABLE and (backoff_ms is None or backoff_ms < 0):
            raise ValueError("retryable errors require backoff_ms >= 0")
        self.error_class = error_class
        self.code = code
        self.message = message
        self.backoff_ms = backoff_ms


class ToolResult:
    """One tool call. Exactly one of ``output`` or ``error`` is set."""

    def __init__(
        self,
        *,
        output: dict[str, Any] | None,
        error: ToolError | None,
        replayed: bool,
    ) -> None:
        if (output is None) == (error is None):
            raise ValueError("exactly one of output or error is required")
        self.output = None if output is None else dict(output)
        self.error = error
        self.replayed = replayed

    @property
    def ok(self) -> bool:
        return self.error is None

    def detached(self) -> ToolResult:
        """Deep copy so a caller cannot mutate a cached payload."""
        return ToolResult(output=_clone_output(self.output), error=self.error, replayed=self.replayed)

    def as_replay(self) -> ToolResult:
        """Deep copy marked as an idempotent replay."""
        return ToolResult(output=_clone_output(self.output), error=self.error, replayed=True)


class RetryableToolError(Exception):
    """A handler raises this when the same call may succeed later."""

    def __init__(self, message: str, *, code: str = "retryable", backoff_ms: int = 200) -> None:
        if backoff_ms < 0:
            raise ValueError("backoff_ms must be >= 0")
        super().__init__(message)
        self.code = code
        self.backoff_ms = backoff_ms


class ToolTimeout(RetryableToolError):
    """The handler gave up because its deadline passed."""

    def __init__(self, message: str = "tool timed out", *, backoff_ms: int = 200) -> None:
        super().__init__(message, code="timeout", backoff_ms=backoff_ms)


class FatalToolError(Exception):
    """A handler raises this when repeating the call will not help."""

    def __init__(self, message: str, *, code: str = "fatal") -> None:
        super().__init__(message)
        self.code = code


class SchemaError(Exception):
    """Arguments or a tool schema failed validation. The message names the path, not the value."""


class SchemaVersionError(Exception):
    """A breaking schema change did not bump the major version."""


class IdempotencyRequired(Exception):
    """A side-effecting tool was registered without an idempotency strategy."""


class ToolConfigurationError(Exception):
    """The registry or Gateway binding is incomplete."""


class GatewayConfigError(Exception):
    """Real Gateway settings are missing or the control-plane call failed."""


def _clone_output(output: dict[str, Any] | None) -> dict[str, Any] | None:
    if output is None:
        return None
    parsed: object = json.loads(json.dumps(output, sort_keys=True))
    if not isinstance(parsed, dict):
        raise ValueError("tool output must be a JSON object")
    cloned: dict[str, Any] = {}
    for key, value in parsed.items():
        if isinstance(key, str):
            cloned[key] = value
    return cloned


def fatal_result(code: str, message: str) -> ToolResult:
    """Build a fatal result with no backoff hint."""
    return ToolResult(
        output=None,
        error=ToolError(error_class=ErrorClass.FATAL, code=code, message=message, backoff_ms=None),
        replayed=False,
    )


def retryable_result(code: str, message: str, backoff_ms: int) -> ToolResult:
    """Build a retryable result with an explicit backoff hint."""
    return ToolResult(
        output=None,
        error=ToolError(
            error_class=ErrorClass.RETRYABLE,
            code=code,
            message=message,
            backoff_ms=backoff_ms,
        ),
        replayed=False,
    )

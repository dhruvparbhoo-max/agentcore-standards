"""In-process idempotency cache for at-least-once tool calls.

``begin`` claims a key before the handler runs. A second caller with the same
key and arguments receives the stored result, or a retryable in-progress
result while the first call still owns the claim. Different arguments are a
conflict and do not run the handler.

``finish`` stores a successful or fatal result. A retryable result releases
the claim so a later attempt can run. The cache lives in the process. A
restart forgets it. Side-effecting tools still need a durable put-if-absent
inside the handler: a deadline does not cancel the handler thread, and the
Lambda target does not receive the agent-side key unless the caller puts it
on the Gateway context.
"""

import hashlib
import json
import threading
from typing import Any

from agentcore_tools.errors import ErrorClass, ToolResult, retryable_result

_IN_PROGRESS_BACKOFF_MS = 50


class IdempotencyConflict(Exception):
    """The same idempotency key was reused with different arguments."""


class IdempotencyClaim:
    """Ownership of one in-flight key. Only the owner calls ``finish``."""

    def __init__(self, tool_name: str, key: str, args_hash: str) -> None:
        self.tool_name = tool_name
        self.key = key
        self.args_hash = args_hash


class IdempotencyStore:
    """Process-local result cache keyed by tool name and idempotency key."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str], _Entry] = {}

    def begin(self, tool_name: str, key: str, args_hash: str) -> IdempotencyClaim | ToolResult:
        """Claim ``key`` or return a replay or an in-progress result.

        The claim is held until ``finish``. Two overlapping calls cannot both
        receive a claim.
        """
        with self._lock:
            entry = self._entries.get((tool_name, key))
            if entry is None:
                self._entries[(tool_name, key)] = _Entry(args_hash)
                return IdempotencyClaim(tool_name, key, args_hash)
            if entry.args_hash != args_hash:
                raise IdempotencyConflict
            if entry.result is None:
                return retryable_result(
                    "idempotency_in_progress",
                    "idempotency key is already running",
                    _IN_PROGRESS_BACKOFF_MS,
                )
            return entry.result.as_replay()

    def finish(self, claim: IdempotencyClaim, result: ToolResult) -> None:
        """Store ``result``, or release the claim when ``result`` is retryable."""
        with self._lock:
            entry = self._entries.get((claim.tool_name, claim.key))
            if entry is None or entry.args_hash != claim.args_hash:
                return
            if result.error is not None and result.error.error_class is ErrorClass.RETRYABLE:
                del self._entries[(claim.tool_name, claim.key)]
                return
            entry.result = result.detached()


class _Entry:
    def __init__(self, args_hash: str) -> None:
        self.args_hash = args_hash
        self.result: ToolResult | None = None


def args_hash(args: dict[str, Any]) -> str:
    """Stable hash of JSON arguments. The arguments themselves are not retained."""
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

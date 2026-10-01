"""In-process idempotency cache for at-least-once tool calls.

The cache remembers a successful or fatal result under ``(tool, key)`` together
with a hash of the arguments. A second call with the same key and arguments
replays that result. A second call with the same key and different arguments
is a conflict and does not run the handler. Retryable failures are not stored,
so a later attempt can run.

The cache lives in the process. A restart forgets it. Side-effecting tools
still need a durable put-if-absent (or a version check) inside the handler.
"""

import hashlib
import json
import threading
from typing import Any

from agentcore_tools.errors import ErrorClass, ToolResult


class IdempotencyConflict(Exception):
    """The same idempotency key was reused with different arguments."""


class IdempotencyStore:
    """Process-local result cache keyed by tool name and idempotency key."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[tuple[str, str], _Entry] = {}

    def lookup(self, tool_name: str, key: str, args_hash: str) -> ToolResult | None:
        """Return a detached replay, or raise ``IdempotencyConflict``.

        ``None`` means the key has not been stored.
        """
        with self._lock:
            entry = self._entries.get((tool_name, key))
            if entry is None:
                return None
            if entry.args_hash != args_hash:
                raise IdempotencyConflict
            return entry.result.as_replay()

    def remember(self, tool_name: str, key: str, args_hash: str, result: ToolResult) -> None:
        """Store ``result`` if this key is new. The first writer wins."""
        if result.error is not None and result.error.error_class is ErrorClass.RETRYABLE:
            return
        with self._lock:
            self._entries.setdefault((tool_name, key), _Entry(args_hash, result.detached()))


class _Entry:
    def __init__(self, args_hash: str, result: ToolResult) -> None:
        self.args_hash = args_hash
        self.result = result


def args_hash(args: dict[str, Any]) -> str:
    """Stable hash of JSON arguments. The arguments themselves are not retained."""
    canonical = json.dumps(args, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

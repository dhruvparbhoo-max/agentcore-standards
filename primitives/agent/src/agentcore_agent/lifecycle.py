"""Busy pings, atomic checkpoints, and a SIGTERM that saves progress.

Copied shapes, adapted to ``BedrockAgentCoreApp``:

- ``run_in_background`` follows aws-samples/sample-social-intelligence-agents
  ``entrypoint.py`` (MIT-0): ``add_async_task`` so ``/ping`` answers
  HealthyBusy, the work runs in a thread under ``contextvars.copy_context``,
  and ``complete_async_task`` runs in ``finally``.
- ``Checkpoint.save`` follows aws/agentcore-cli
  ``src/assets/python/http/bma/base/lifecycle/server.py`` (Apache-2.0):
  write ``state.json.tmp``, then replace ``state.json`` atomically.
- ``install_shutdown`` follows the same file's ``serve()``: SIGTERM and SIGINT
  call the shutdown hook, then exit 0.

The microVM disk dies with the session. A resumable pattern also writes its
checkpoint to the job row; this file is the in-session copy.
"""

from __future__ import annotations

import contextvars
import json
import logging
import signal
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from types import FrameType
from typing import Any, Protocol

STATE_FILE = "state.json"
_log = logging.getLogger("agentcore.lifecycle")


class AsyncTaskHost(Protocol):
    def add_async_task(self, name: str, metadata: dict[str, Any] | None = None) -> int: ...

    def complete_async_task(self, task_id: int) -> bool: ...


def run_in_background(
    app: AsyncTaskHost,
    name: str,
    work: Callable[[], None],
    *,
    metadata: Mapping[str, Any] | None = None,
    on_done: Callable[[bool], None] | None = None,
) -> tuple[int, threading.Thread]:
    """Start ``work`` in a thread. The session reports HealthyBusy until it returns."""
    task_id = app.add_async_task(name, dict(metadata or {}))
    snapshot = contextvars.copy_context()

    def target() -> None:
        succeeded = False
        try:
            work()
            succeeded = True
        except Exception:
            _log.exception("background task failed", extra={"action": name})
        finally:
            try:
                if on_done is not None:
                    on_done(succeeded)
            finally:
                app.complete_async_task(task_id)

    thread = threading.Thread(target=lambda: snapshot.run(target), daemon=True)
    thread.start()
    return task_id, thread


class Checkpoint:
    """One JSON file under ``directory``. A crash mid-write leaves the previous file intact."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @property
    def path(self) -> Path:
        return self.directory / STATE_FILE

    def save(self, state: Mapping[str, Any]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        temporary = self.directory / f"{STATE_FILE}.tmp"
        temporary.write_text(json.dumps(dict(state), sort_keys=True), encoding="utf-8")
        temporary.replace(self.path)

    def load(self) -> dict[str, Any] | None:
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, ValueError):
            _log.warning("checkpoint unreadable", extra={"action": "checkpoint_load"})
            return None
        return saved if isinstance(saved, dict) else None


def install_shutdown(on_shutdown: Callable[[], None]) -> None:
    """Save progress on SIGTERM or SIGINT, then exit 0. Runtime sends SIGTERM before it stops a session."""

    def handle(signal_number: int, _frame: FrameType | None) -> None:
        _log.info("signal received", extra={"action": "shutdown", "decision": str(signal_number)})
        try:
            on_shutdown()
        finally:
            raise SystemExit(0)

    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)

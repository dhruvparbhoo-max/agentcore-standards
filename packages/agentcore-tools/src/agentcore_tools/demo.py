"""Idempotent demo tool for the Lambda target path.

``put_record`` stores a row by natural key with put-if-absent. A second call
with the same ``record_id`` returns the original row and does not overwrite it.
The registry's idempotency key is a separate at-least-once guard: the same key
does not call the handler twice.
"""

import threading
from collections.abc import Mapping
from typing import Any

from agentcore_tools.errors import FatalToolError
from agentcore_tools.registry import ToolRegistry

DEMO_AGENT_VERSION = "0.1.0"
PUT_RECORD = "put_record"
LAMBDA_TARGET = "records"

PUT_RECORD_SCHEMA: dict[str, Any] = {
    "additionalProperties": False,
    "properties": {
        "body": {"description": "Record body.", "type": "string"},
        "record_id": {"description": "Natural key for the record.", "type": "string"},
    },
    "required": ["record_id", "body"],
    "type": "object",
}


class RecordStore:
    """Process-local put-if-absent store. A durable deploy uses the same contract."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[str, dict[str, str]] = {}

    def put_if_absent(self, record_id: str, body: str) -> tuple[dict[str, str], bool]:
        """Insert ``record_id`` once. Return the stored row and whether this call created it."""
        if not record_id or not record_id.strip():
            raise FatalToolError("record_id is required", code="invalid_record")
        with self._lock:
            existing = self._rows.get(record_id)
            if existing is not None:
                return dict(existing), False
            row = {"body": body, "record_id": record_id}
            self._rows[record_id] = row
            return dict(row), True

    def get(self, record_id: str) -> dict[str, str] | None:
        with self._lock:
            row = self._rows.get(record_id)
            return None if row is None else dict(row)

    def __len__(self) -> int:
        with self._lock:
            return len(self._rows)


class DemoTools:
    """A registry with one Lambda target and the ``put_record`` tool. Policy starts empty."""

    def __init__(self) -> None:
        self.executions = 0
        self.store = RecordStore()
        self.registry = ToolRegistry()
        self._register()

    def _register(self) -> None:
        store = self.store

        @self.registry.tool(
            name=PUT_RECORD,
            schema=PUT_RECORD_SCHEMA,
            description="Put a record by its natural key. The same record id does not create a second row.",
            idempotent=True,
            side_effecting=True,
            schema_version="1.0.0",
        )
        def put_record(args: Mapping[str, Any]) -> Mapping[str, Any]:
            self.executions += 1
            record, created = store.put_if_absent(str(args["record_id"]), str(args["body"]))
            return {"created": created, "record": record}

        self.registry.add_lambda_target(LAMBDA_TARGET, tools=(PUT_RECORD,))


def build_demo_registry() -> DemoTools:
    """Build the default Gateway + Lambda demo. Nothing is permitted until the caller says so."""
    return DemoTools()

"""``submit_change`` is a change action. The loop pauses; the handler runs after consume."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agentcore_agent import ToolSpec
from submit_change.handler import handler as submit_change_handler

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["idempotency_key", "actor_id", "summary"],
    "properties": {
        "idempotency_key": {"type": "string", "minLength": 8},
        "actor_id": {"type": "string"},
        "summary": {"type": "string"},
    },
}


def _run(arguments: Mapping[str, Any]) -> Any:
    return submit_change_handler(dict(arguments), None)


TOOLS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="submit_change",
        description="Record a requested change. Needs a person's approval first.",
        input_schema=SCHEMA,
        handler=_run,
        action="change",
    ),
)

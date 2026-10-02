"""JSON logs for one agent turn.

Field names match DESIGN §1.4: runtime session, actor, agent version, request id,
tool name, latency, and error class. Payloads must not carry secrets.

``runtimeSessionId`` is ``hash_session_id`` of the raw session id (first 32 hex
characters of SHA-256). The same value is span attribute ``runtime.session_id``.
Callers pass the raw id. The log line does not store it next to ``actorId``.
"""

import json
import logging
from typing import Any

from agentcore_tracing.session_id import hash_session_id

LOGGER_NAME = "agentcore.turn"


class TurnLog:
    """One structured log line for a turn."""

    def __init__(
        self,
        *,
        runtime_session_id: str,
        actor_id: str,
        agent_version: str,
        request_id: str,
        latency_ms: float,
        tool_name: str | None = None,
        error_class: str | None = None,
    ) -> None:
        self.runtime_session_id = runtime_session_id
        self.actor_id = actor_id
        self.agent_version = agent_version
        self.request_id = request_id
        self.latency_ms = latency_ms
        self.tool_name = tool_name
        self.error_class = error_class

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "actorId": self.actor_id,
            "agentVersion": self.agent_version,
            "errorClass": self.error_class,
            "latencyMs": round(self.latency_ms, 3),
            "requestId": self.request_id,
            "runtimeSessionId": hash_session_id(self.runtime_session_id),
        }
        if self.tool_name is not None:
            body["toolName"] = self.tool_name
        return body


def emit_turn_log(record: TurnLog) -> dict[str, Any]:
    """Emit ``record`` as one JSON line on the ``agentcore.turn`` logger."""
    payload = record.as_dict()
    logging.getLogger(LOGGER_NAME).info(json.dumps(payload, sort_keys=True))
    return payload

"""Shared HTTP shapes for the API Gateway HTTP API (payload format 2.0)."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from typing import Any

from agentcore_front_door.door import CallResult
from agentcore_front_door.governance import Refused


def body_of(event: Mapping[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError("body must be a JSON object")
    return decoded


def respond(status: int, body: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json", "cache-control": "no-store"},
        "body": json.dumps(dict(body), default=str),
    }


def refused(exc: Refused) -> dict[str, Any]:
    return respond(exc.status, {"error": exc.code, "message": str(exc)})


def result_body(result: CallResult) -> dict[str, Any]:
    return {
        "call_id": result.call_id,
        "session_id": result.session_id,
        "release_id": result.release_id,
        "turn": result.turn,
        "result": dict(result.body),
        "cost": {"usd": result.cost.usd, "source": result.cost.source},
    }

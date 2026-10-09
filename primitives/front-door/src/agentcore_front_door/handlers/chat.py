"""``POST /agents/{agent}/invoke``: chat and API callers with a signed-in user.

The HTTP API's JWT authorizer rejects unsigned requests before this runs; the
handler verifies the token again so the user id, team, and tenant come from a
token this code checked, never from the body.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agentcore_front_door import wiring
from agentcore_front_door.caller import Unauthenticated, bearer
from agentcore_front_door.door import CallRequest
from agentcore_front_door.governance import Refused
from agentcore_front_door.handlers.http import body_of, refused, respond, result_body


def handler(event: Mapping[str, Any], _context: Any = None) -> dict[str, Any]:
    try:
        caller = wiring.verifier().verify(bearer(event.get("headers")))
    except Unauthenticated as exc:
        return respond(401, {"error": "unauthenticated", "message": str(exc)})
    agent = str((event.get("pathParameters") or {}).get("agent", ""))
    try:
        body = body_of(event)
    except ValueError:
        return respond(400, {"error": "bad_body", "message": "body must be a JSON object"})
    raw_payload = body.get("payload")
    payload: Mapping[str, Any] = raw_payload if isinstance(raw_payload, Mapping) else {"prompt": body.get("prompt", "")}
    source = "api" if body.get("source") == "api" else "chat"
    session_id = body.get("session_id") if isinstance(body.get("session_id"), str) else None
    try:
        result = wiring.door().call(
            CallRequest(caller=caller, agent=agent, payload=payload, source=source, session_id=session_id)
        )
    except Refused as exc:
        return refused(exc)
    return respond(result.status_code, result_body(result))

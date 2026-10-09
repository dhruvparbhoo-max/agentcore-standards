"""Job, schedule, event, and eval callers. Invoked by the triggers worker with IAM, never from the internet.

The event is ``{"source": "job", "job": {...}, "payload": {...}}``. The job row
names the service identity and the stored consent it runs under. A job with no
consent record does not start.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agentcore_front_door import wiring
from agentcore_front_door.caller import Unauthenticated, service_caller
from agentcore_front_door.door import CallRequest
from agentcore_front_door.governance import Refused
from agentcore_front_door.handlers.http import result_body

JOB_SOURCES = ("job", "schedule", "event", "eval")


def handler(event: Mapping[str, Any], _context: Any = None) -> dict[str, Any]:
    job = event.get("job")
    if not isinstance(job, Mapping):
        return {"ok": False, "status": 400, "error": "bad_event", "message": "event.job is required"}
    try:
        caller = service_caller(job)
    except Unauthenticated as exc:
        return {"ok": False, "status": 401, "error": "unauthenticated", "message": str(exc)}
    source = str(event.get("source", "job"))
    if source not in JOB_SOURCES:
        return {"ok": False, "status": 400, "error": "bad_source", "message": f"source must be one of {JOB_SOURCES}"}
    payload = event.get("payload")
    try:
        result = wiring.door().call(
            CallRequest(
                caller=caller,
                agent=str(job.get("agent", "")),
                payload=payload if isinstance(payload, Mapping) else {},
                source=source,
                session_id=str(job["session_id"]) if job.get("session_id") else None,
                job_id=str(job.get("id", "")),
            )
        )
    except Refused as exc:
        return {"ok": False, "status": exc.status, "error": exc.code, "message": str(exc)}
    return {"ok": 200 <= result.status_code < 300, "status": result.status_code, **result_body(result)}

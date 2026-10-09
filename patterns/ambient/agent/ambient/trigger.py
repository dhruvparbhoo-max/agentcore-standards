"""An event becomes a job, then a worker calls the agent through the same session API.

The worker does not call AgentCore Runtime directly. In a deploy the front door
is that call; locally ``AgentSession.run`` is the same loop the door would invoke.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import uuid4

from agentcore_agent import AgentSession, TurnResult

from ambient.jobs import Job, JobStore

WORKER = "ambient-worker"


def accept_event(store: JobStore, event: Mapping[str, Any], *, release_id: str) -> Job:
    """Conditional create. A duplicate source+event returns the existing row and starts nothing."""
    source = str(event["source"])
    event_id = str(event["event_id"])
    existing = store.by_event(source, event_id)
    if existing is not None:
        return existing
    job = Job(
        job_id=f"job-{uuid4().hex[:16]}",
        source=source,
        event_id=event_id,
        status="queued",
        release_id=release_id,
        payload=dict(event.get("payload") or {}),
        on_behalf_of=str(event.get("on_behalf_of") or ""),
        consent_ref=str(event.get("consent_ref") or "consent#ambient"),
    )
    created = store.create(job)
    return created if created is not None else store.by_event(source, event_id)  # type: ignore[return-value]


def run_job(store: JobStore, session: AgentSession, job: Job, *, session_id: str) -> TurnResult:
    """Start or resume one attempt. A paused change waits on the job row, not the microVM."""
    if job.status in {"succeeded", "failed", "cancelled"}:
        raise ValueError(f"job {job.job_id} is {job.status}")
    attempt = job.attempt + 1
    store.update(job.job_id, status="running", attempt=attempt, session_id=session_id)
    prompt = str(job.payload.get("prompt") or "")
    result = session.run(prompt, session_id=session_id, actor_id=WORKER)
    if result.status == "paused":
        store.update(
            job.job_id,
            status="waiting_for_approval",
            approval_id=result.ticket.token_id if result.ticket else "",
            checkpoint={"prompt": prompt},
        )
        return result
    store.update(job.job_id, status="succeeded" if result.status == "completed" else "failed")
    return result

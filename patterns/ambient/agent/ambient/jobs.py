"""Job rows for ambient work. The queue and this table are not agent memory.

Idempotency for events is source plus event id. A second delivery of that pair
finds the existing row and does not start another job. Status values follow
docs/design/library.md "Job queue".
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

Status = Literal["queued", "running", "waiting_for_approval", "succeeded", "failed", "cancelled"]
TERMINAL = frozenset({"succeeded", "failed", "cancelled"})


@dataclass(frozen=True)
class Job:
    job_id: str
    source: str
    event_id: str
    status: Status
    release_id: str
    attempt: int = 0
    session_id: str = ""
    checkpoint: dict[str, Any] = field(default_factory=dict)
    approval_id: str = ""
    payload: dict[str, Any] = field(default_factory=dict)
    on_behalf_of: str = ""
    consent_ref: str = ""


class JobStore:
    """Process-local jobs. A DynamoDB table with a conditional put replaces this in a deploy."""

    def __init__(self) -> None:
        self._by_event: dict[tuple[str, str], Job] = {}
        self._by_id: dict[str, Job] = {}

    def create(self, job: Job) -> Job | None:
        """Store ``job`` unless that source+event already exists. Return None on a duplicate."""
        key = (job.source, job.event_id)
        if key in self._by_event:
            return None
        self._by_event[key] = job
        self._by_id[job.job_id] = job
        return job

    def get(self, job_id: str) -> Job:
        return self._by_id[job_id]

    def by_event(self, source: str, event_id: str) -> Job | None:
        return self._by_event.get((source, event_id))

    def update(self, job_id: str, **changes: Any) -> Job:
        current = self._by_id[job_id]
        updated = replace(current, **changes)
        self._by_id[job_id] = updated
        self._by_event[(updated.source, updated.event_id)] = updated
        return updated

    def __len__(self) -> int:
        return len(self._by_id)

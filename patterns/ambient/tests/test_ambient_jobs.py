"""Duplicate events are a no-op. A change waits on the job row."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from agentcore_agent import build_agent, load_pattern
from agentcore_agent.golden import load_golden, score_golden
from ambient.jobs import JobStore
from ambient.script import WORKER, work_script
from ambient.tools import TOOLS
from ambient.trigger import accept_event, run_job

PATTERN = Path(__file__).resolve().parents[1]
SESSION = "ambient-session-" + "0" * 24
NOW = datetime(2026, 10, 9, tzinfo=UTC)
INVOICE = {
    "source": "invoices",
    "event_id": "evt-invoice-pack-0001",
    "payload": {"prompt": "index the new invoice pack"},
    "consent_ref": "consent#ambient",
    "on_behalf_of": "alice",
}


def test_duplicate_event_does_not_start_a_second_job() -> None:
    store = JobStore()
    first = accept_event(store, INVOICE, release_id="rel-1")
    second = accept_event(store, INVOICE, release_id="rel-1")
    assert first.job_id == second.job_id
    assert first.status == "queued"
    assert len(store) == 1


def test_change_event_pauses_and_waits_on_the_job_row() -> None:
    store = JobStore()
    session = build_agent(load_pattern(PATTERN), tools=TOOLS, script=work_script())
    job = accept_event(
        store,
        {
            "source": "vendors",
            "event_id": "evt-vendor-close-0001",
            "payload": {"prompt": "please change the vendor account to closed"},
            "consent_ref": "consent#ambient",
        },
        release_id="rel-1",
    )
    result = run_job(store, session, job, session_id=SESSION)
    waiting = store.get(job.job_id)
    assert result.status == "paused"
    assert waiting.status == "waiting_for_approval"
    assert waiting.approval_id == result.ticket.token_id if result.ticket else ""
    assert waiting.attempt == 1
    session.approvals.decide(waiting.approval_id, approved=True, approver_id="reviewer-1", now=NOW)
    done = session.resume(session_id=SESSION, actor_id=WORKER, token_id=waiting.approval_id, approved=True)
    store.update(job.job_id, status="succeeded")
    assert done.status == "completed"
    assert store.get(job.job_id).status == "succeeded"


@pytest.mark.parametrize("framework", ["create_agent", "strands"])
def test_golden_set_passes_offline_on_both_frameworks(framework: str) -> None:
    config = load_pattern(PATTERN)
    config = type(config)(root=config.root, raw={**config.raw, "framework": framework})
    session = build_agent(config, tools=TOOLS, script=work_script())
    golden = load_golden(PATTERN / "eval" / "golden_set.json")
    result = score_golden(
        golden,
        session,
        session_id_for=lambda case, run: f"{case}-{run}".ljust(40, "0"),
        runs_per_case=int(config.section("eval")["runs_per_case"]),
    )
    failures = [case for case in result.cases if not case.passed]
    assert not failures, failures
    assert result.score >= float(config.section("eval")["threshold"])

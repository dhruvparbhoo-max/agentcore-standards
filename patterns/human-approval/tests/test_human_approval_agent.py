"""Pause, resume, reject, and the four ask wrappers."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from agentcore_agent import PauseRequest, build_agent, load_pattern
from agentcore_agent.config import ACTOR_HEADER
from agentcore_agent.golden import load_golden, score_golden
from bedrock_agentcore.runtime.context import RequestContext
from human_approval.ask import WAYS, ask
from human_approval.script import DEFAULT_ACTOR, change_script
from human_approval.tools import TOOLS

PATTERN = Path(__file__).resolve().parents[1]
SESSION = "human-approval-session-" + "0" * 16
NOW = datetime(2026, 10, 9, tzinfo=UTC)


@pytest.fixture
def entrypoint(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("AGENTCORE_MODEL", "scripted")
    from human_approval import app

    monkeypatch.setattr(app, "_agent", None)
    return app.invoke


def _context(actor: str = DEFAULT_ACTOR) -> RequestContext:
    return RequestContext(session_id=SESSION, request_headers={ACTOR_HEADER: actor}, request=None)


def test_entrypoint_pauses_on_change(entrypoint: Any) -> None:
    body = entrypoint({"prompt": "please change the folder name to archive"}, _context())
    assert body["status"] == "paused"
    assert body["approval"]["tool"] == "submit_change"
    assert body["approval"]["action"] == "change"
    assert body["approval"]["actor_id"] == DEFAULT_ACTOR


def test_entrypoint_resume_after_another_person_approves(entrypoint: Any) -> None:
    from human_approval import app

    paused = entrypoint({"prompt": "please change the folder name to archive"}, _context())
    token = paused["approval"]["token_id"]
    app.agent().approvals.decide(token, approved=True, approver_id="reviewer-1", now=NOW)
    done = entrypoint({"resume": {"token_id": token, "approved": True}}, _context())
    assert done["status"] == "completed"
    assert "created" in done["result"] or "change-" in done["result"]


def test_actor_cannot_approve_own_change(entrypoint: Any) -> None:
    from agentcore_approvals import ApprovalError
    from human_approval import app

    paused = entrypoint({"prompt": "please change the folder name to archive"}, _context())
    token = paused["approval"]["token_id"]
    with pytest.raises(ApprovalError):
        app.agent().approvals.decide(token, approved=True, approver_id=DEFAULT_ACTOR, now=NOW)


@pytest.mark.parametrize("way", WAYS)
def test_every_ask_opens_the_same_kind_of_ticket(way: str) -> None:
    session = build_agent(load_pattern(PATTERN), tools=TOOLS, script=change_script())
    ticket = ask(
        way,
        session,
        PauseRequest(
            tool="submit_change",
            arguments={"idempotency_key": "change-key-ask-01", "actor_id": DEFAULT_ACTOR, "summary": "x"},
            actor_id=DEFAULT_ACTOR,
            action="change",
            session_id=SESSION,
            reviewers=1,
            expire_s=3600,
            summary="Rename the folder",
        ),
    )
    assert ticket.tool == "submit_change" and ticket.action == "change"
    assert ticket.actor_id == DEFAULT_ACTOR
    assert ticket.summary == "Rename the folder"


@pytest.mark.parametrize("framework", ["create_agent", "strands"])
def test_golden_set_passes_offline_on_both_frameworks(framework: str) -> None:
    config = load_pattern(PATTERN)
    config = type(config)(root=config.root, raw={**config.raw, "framework": framework})
    session = build_agent(config, tools=TOOLS, script=change_script())
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

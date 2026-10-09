"""Unit tests: retrieve wrapper, both code frameworks, and the offline golden score."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from agentcore_agent import build_agent, echo_script, load_pattern
from agentcore_agent.config import ACTOR_HEADER
from agentcore_agent.golden import load_golden, score_golden
from bedrock_agentcore.runtime.context import RequestContext
from policy_qa.knowledge import EMPTY, retrieve
from policy_qa.session import KnowledgeSession
from policy_qa.tools import TOOLS

PATTERN = Path(__file__).resolve().parents[1]
SESSION = "policy-qa-session-" + "0" * 22
ALICE = "acme/employee/alice"


@pytest.fixture
def entrypoint(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("AGENTCORE_MODEL", "scripted")
    from policy_qa import app

    monkeypatch.setattr(app, "_agent", None)
    return app.invoke


def _context(actor: str = ALICE) -> RequestContext:
    return RequestContext(session_id=SESSION, request_headers={ACTOR_HEADER: actor}, request=None)


def test_entrypoint_cites_a_leave_policy(entrypoint: Any) -> None:
    body = entrypoint({"prompt": "How many paid leave days do full-time employees get?"}, _context())
    assert body["status"] == "completed"
    assert "HR-Leave-2024" in body["result"]
    assert body["release_id"] == "unreleased"


def test_entrypoint_empty_sentence(entrypoint: Any) -> None:
    body = entrypoint({"prompt": "What is the quantum teleportation allowance?"}, _context())
    assert body["result"] == EMPTY
    assert "usage" not in body


def test_entrypoint_refuses_an_unverified_caller(entrypoint: Any) -> None:
    with pytest.raises(ValueError, match="actor"):
        entrypoint({"prompt": "leave days"}, _context(actor=""))


def test_employee_does_not_see_finance_or_globex() -> None:
    hits = retrieve("expense claim receipt 50 pounds", ALICE)
    ids = {item.passage_id for item in hits}
    assert "FIN-Expense-2024" not in ids
    assert "GLOBEX-Leave-2024" not in ids


def test_globex_actor_does_not_see_acme() -> None:
    hits = retrieve("paid leave days", "globex/employee/sam")
    ids = {item.passage_id for item in hits}
    assert ids == {"GLOBEX-Leave-2024"}


@pytest.mark.parametrize("framework", ["create_agent", "strands"])
def test_golden_set_passes_offline_on_both_frameworks(framework: str) -> None:
    config = load_pattern(PATTERN)
    config = type(config)(root=config.root, raw={**config.raw, "framework": framework})
    session = KnowledgeSession(build_agent(config, tools=TOOLS, script=echo_script()))
    golden = load_golden(PATTERN / "eval" / "golden_set.json")
    result = score_golden(
        golden,
        session,  # type: ignore[arg-type]
        session_id_for=lambda case, run: f"{case}-{run}".ljust(40, "0"),
        runs_per_case=int(config.section("eval")["runs_per_case"]),
    )
    failures = [case for case in result.cases if not case.passed]
    assert not failures, failures
    assert result.score >= float(config.section("eval")["threshold"])
    assert result.score >= float(config.section("eval")["groundedness"])

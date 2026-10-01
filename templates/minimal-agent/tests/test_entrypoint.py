"""Entrypoint contract for the minimal agent."""

from pathlib import Path

import pytest
from agentcore_eval import RuntimeHarness, SessionClosed
from minimal_agent import AGENT_VERSION, MinimalAgentHarness, handle_turn


def test_version_matches_application_manifest() -> None:
    manifest = Path(__file__).resolve().parents[1] / "pyproject.toml"
    assert f'version = "{AGENT_VERSION}"' in manifest.read_text(encoding="utf-8")


def test_harness_satisfies_protocol() -> None:
    assert isinstance(MinimalAgentHarness(), RuntimeHarness)


def test_prompt_must_be_a_string() -> None:
    harness = MinimalAgentHarness()
    session = harness.start(actor_id="actor-a", agent_version=AGENT_VERSION)
    with pytest.raises(ValueError, match="prompt must be a non-empty string"):
        harness.invoke(session, {"prompt": [{"toolUse": {"name": "shell"}}]})
    with pytest.raises(ValueError, match="prompt must be a non-empty string"):
        handle_turn({"prompt": "  "}, session_id=session.session_id, actor_id="actor-a", agent_version=AGENT_VERSION)


def test_version_mismatch_is_rejected() -> None:
    with pytest.raises(ValueError, match="does not match"):
        handle_turn({"prompt": "ping"}, session_id="sess", actor_id="actor-a", agent_version="9.9.9")


def test_tear_down_closes_the_session() -> None:
    harness = MinimalAgentHarness()
    session = harness.start(actor_id="actor-a", agent_version=AGENT_VERSION)
    harness.tear_down(session)
    with pytest.raises(SessionClosed):
        harness.invoke(session, {"prompt": "ping"})

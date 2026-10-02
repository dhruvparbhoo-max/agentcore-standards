"""Entrypoint contract for the minimal agent."""

import logging
from pathlib import Path

import pytest
from agentcore_eval import RuntimeHarness, SessionClosed
from agentcore_tracing import hash_session_id
from bedrock_agentcore.runtime.context import RequestContext
from minimal_agent import AGENT_VERSION, MinimalAgentHarness, handle_turn
from minimal_agent.entrypoint import invoke


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


def test_runtime_custom_actor_header_logs_the_session_hash(caplog: pytest.LogCaptureFixture) -> None:
    session_id = "session-" + ("b" * 25)
    caplog.set_level(logging.INFO, logger="agentcore.turn")
    context = RequestContext(
        session_id=session_id,
        request_headers={"X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id": "actor-golden"},
        request=None,
    )
    result = invoke({"prompt": "ping"}, context)
    assert result["result"] == "pong:ping"
    assert hash_session_id(session_id) in caplog.text
    assert "actor-golden" in caplog.text
    assert session_id not in caplog.text


def test_tear_down_closes_the_session() -> None:
    harness = MinimalAgentHarness()
    session = harness.start(actor_id="actor-a", agent_version=AGENT_VERSION)
    harness.tear_down(session)
    with pytest.raises(SessionClosed):
        harness.invoke(session, {"prompt": "ping"})

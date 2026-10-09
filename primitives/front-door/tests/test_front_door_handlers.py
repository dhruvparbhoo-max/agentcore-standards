from __future__ import annotations

import json
import time
from collections.abc import Iterator
from typing import Any

import jwt
import pytest
from agentcore_front_door import JwtVerifier, MemoryStore, Switch, cli, wiring
from agentcore_front_door.handlers import chat, job
from cryptography.hazmat.primitives.asymmetric import rsa
from front_door_fakes import FakeRuntime, make_door, policy

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
ISSUER = "https://issuer.example.invalid"


def _token(sub: str = "alice") -> str:
    now = int(time.time())
    return jwt.encode({"sub": sub, "iss": ISSUER, "iat": now, "exp": now + 60}, KEY, algorithm="RS256")


@pytest.fixture
def wired(monkeypatch: pytest.MonkeyPatch, runtime: FakeRuntime, store: MemoryStore) -> Iterator[MemoryStore]:
    door = make_door(runtime, store, policies=[policy(), policy(agent="ambient", acts_as="service", tools=[])])
    verifier = JwtVerifier(issuer=ISSUER, signing_key_for=lambda _t: KEY.public_key())
    monkeypatch.setattr(wiring, "door", lambda: door)
    monkeypatch.setattr(wiring, "verifier", lambda: verifier)
    yield store


def _chat(token: str | None, body: dict[str, Any], agent: str = "policy-qa") -> dict[str, Any]:
    headers = {"authorization": f"Bearer {token}"} if token else {}
    event = {"headers": headers, "pathParameters": {"agent": agent}, "body": json.dumps(body)}
    return chat.handler(event)


def test_chat_returns_the_bound_session_and_result(wired: MemoryStore) -> None:
    response = _chat(_token(), {"prompt": "hello"})
    body = json.loads(response["body"])
    assert response["statusCode"] == 200
    assert body["result"]["result"] == "ok" and len(body["session_id"]) >= 33
    follow_up = json.loads(_chat(_token(), {"prompt": "again", "session_id": body["session_id"]})["body"])
    assert follow_up["session_id"] == body["session_id"] and follow_up["turn"] == 2


def test_chat_without_a_token_is_401(wired: MemoryStore) -> None:
    assert _chat(None, {"prompt": "x"})["statusCode"] == 401


def test_chat_with_someone_elses_session_is_400(wired: MemoryStore) -> None:
    session = json.loads(_chat(_token("alice"), {"prompt": "x"})["body"])["session_id"]
    response = _chat(_token("mallory"), {"prompt": "x", "session_id": session})
    assert response["statusCode"] == 400 and json.loads(response["body"])["error"] == "bad_session"


def test_switched_off_agent_is_503(wired: MemoryStore) -> None:
    wired.put_switch(Switch(scope="agent", name="policy-qa", enabled=False, reason="drill"))
    response = _chat(_token(), {"prompt": "x"})
    assert response["statusCode"] == 503


def test_job_handler_runs_under_the_stored_service_identity(wired: MemoryStore) -> None:
    event = {
        "source": "job",
        "job": {"id": "job-9", "agent": "ambient", "service_identity": "triggers", "consent_ref": "consent#9"},
        "payload": {"prompt": "do it"},
    }
    result = job.handler(event)
    assert result["ok"] is True
    assert wired.audit[0]["job_id"] == "job-9"


def test_job_without_consent_is_refused(wired: MemoryStore) -> None:
    event = {"job": {"id": "j", "agent": "ambient", "service_identity": "triggers"}}
    assert job.handler(event)["status"] == 401


def test_cli_switch_off_needs_a_reason_and_records_who(capsys: pytest.CaptureFixture[str]) -> None:
    store = MemoryStore()
    assert cli.main(["switch", "off", "agent", "policy-qa", "--by", "alice"], store=store) == 2
    assert cli.main(["switch", "off", "agent", "policy-qa", "--by", "alice", "--reason", "drill"], store=store) == 0
    switch = store.switch("agent", "policy-qa")
    assert switch is not None and not switch.enabled and switch.set_by == "alice"
    assert cli.main(["switches"], store=store) == 0
    assert "policy-qa" in capsys.readouterr().out

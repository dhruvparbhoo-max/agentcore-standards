"""Drive the local front door the way API Gateway and the triggers worker would.

Run by ``make local`` after the compose stack is up. Each check prints PASS or
FAIL; any FAIL exits 1. The front door talks to DynamoDB Local and the template
agent container, so this proves the wiring, not AgentCore Runtime.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agentcore_front_door import DynamoStore, Switch
from agentcore_front_door.local import mint, write_key_pair

KEYS = Path(__file__).resolve().parents[1] / "build" / "local"
RIE_PATH = "/2015-03-31/functions/function/invocations"


def invoke(url: str, event: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(url + RIE_PATH, data=json.dumps(event).encode(), method="POST")
    with urllib.request.urlopen(request, timeout=60) as response:
        decoded = json.loads(response.read())
    if not isinstance(decoded, dict):
        raise ValueError("handler must return an object")
    return decoded


def chat_event(token: str, agent: str, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "headers": {"authorization": f"Bearer {token}"},
        "pathParameters": {"agent": agent},
        "body": json.dumps(body),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chat-url", default="http://localhost:9002")
    parser.add_argument("--job-url", default="http://localhost:9003")
    parser.add_argument("--agent", default="_template")
    parser.add_argument("--dynamodb", default="http://localhost:8000")
    args = parser.parse_args()
    os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-2")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")
    private, _public = write_key_pair(KEYS)
    alice = mint(private, {"sub": "alice", "custom:team": "platform"})
    mallory = mint(private, {"sub": "mallory", "custom:team": "platform"})
    store = DynamoStore.from_names("front-door-state", "front-door-audit", endpoint_url=args.dynamodb)
    failures = 0

    def check(name: str, condition: Callable[[], bool]) -> None:
        nonlocal failures
        try:
            ok = condition()
        except Exception as exc:
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
            failures += 1
            return
        print(f"{'PASS' if ok else 'FAIL'} {name}")
        failures += not ok

    first = invoke(args.chat_url, chat_event(alice, args.agent, {"prompt": "hello"}))
    body = json.loads(first.get("body", "{}"))
    session = str(body.get("session_id", ""))
    check("chat turn answers through the agent", lambda: first["statusCode"] == 200 and "pong" in json.dumps(body))
    check("session id is bound and at least 33 characters", lambda: len(session) >= 33)
    second = invoke(args.chat_url, chat_event(alice, args.agent, {"prompt": "again", "session_id": session}))
    check("same user continues the session", lambda: json.loads(second["body"])["turn"] == 2)
    stolen = invoke(args.chat_url, chat_event(mallory, args.agent, {"prompt": "x", "session_id": session}))
    check("another user's session id is refused", lambda: stolen["statusCode"] == 400)
    short = invoke(args.chat_url, chat_event(alice, args.agent, {"prompt": "x", "session_id": "short"}))
    check("a short session id is refused", lambda: short["statusCode"] == 400)
    unsigned = invoke(args.chat_url, chat_event("not-a-token", args.agent, {"prompt": "x"}))
    check("an unsigned caller is refused", lambda: unsigned["statusCode"] == 401)

    store.put_switch(Switch(scope="agent", name=args.agent, enabled=False, reason="smoke", set_by="smoke"))
    off = invoke(args.chat_url, chat_event(alice, args.agent, {"prompt": "x"}))
    store.put_switch(Switch(scope="agent", name=args.agent, enabled=True, reason="smoke", set_by="smoke"))
    check("kill switch off refuses the call", lambda: off["statusCode"] == 503)
    back = invoke(args.chat_url, chat_event(alice, args.agent, {"prompt": "x"}))
    check("kill switch on lets calls through", lambda: back["statusCode"] == 200)

    job = {"id": "job-smoke", "agent": args.agent, "service_identity": "triggers", "consent_ref": "consent#smoke"}
    no_user = invoke(args.job_url, {"source": "job", "job": job, "payload": {"prompt": "hello"}})
    check("a user-acting agent refuses a bare service caller", lambda: no_user["error"] == "needs_user")
    consented = invoke(
        args.job_url,
        {"source": "job", "job": {**job, "on_behalf_of": "alice"}, "payload": {"prompt": "hello"}},
    )
    check("a job acting for a stored consent runs", lambda: consented["ok"] is True)

    import boto3

    audit = boto3.resource("dynamodb", endpoint_url=args.dynamodb).Table("front-door-audit").scan()["Items"]
    phases = {str(item.get("phase")) for item in audit if item.get("kind") == "audit"}
    check("audit rows for accepted, completed, and refused", lambda: {"accepted", "completed", "refused"} <= phases)
    check("a cost record per completed call", lambda: any(item.get("kind") == "cost" for item in audit))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

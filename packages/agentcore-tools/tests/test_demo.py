"""Demo Lambda tool: wrapper replay and put-if-absent on the natural key."""

import json
from pathlib import Path

from agentcore_tools import DEMO_AGENT_VERSION, PUT_RECORD, Policy, build_demo_registry, write_double_invoke_evidence


def test_same_idempotency_key_is_one_side_effect() -> None:
    demo = build_demo_registry()
    policy = Policy()
    policy.permit(DEMO_AGENT_VERSION, PUT_RECORD)
    demo.registry.bind_gateway("gateway-local", policy=policy)
    args = {"body": "hello", "record_id": "rec-1"}
    first = demo.registry.invoke_tool(
        PUT_RECORD,
        args,
        agent_version=DEMO_AGENT_VERSION,
        idempotency_key="k1",
    )
    second = demo.registry.invoke_tool(
        PUT_RECORD,
        args,
        agent_version=DEMO_AGENT_VERSION,
        idempotency_key="k1",
    )
    assert first.output is not None
    assert first.output["created"] is True
    assert second.replayed is True
    assert second.output == first.output
    assert demo.executions == 1
    assert len(demo.store) == 1


def test_two_keys_with_one_record_id_do_not_overwrite() -> None:
    demo = build_demo_registry()
    policy = Policy()
    policy.permit(DEMO_AGENT_VERSION, PUT_RECORD)
    demo.registry.bind_gateway("gateway-local", policy=policy)
    first = demo.registry.invoke_tool(
        PUT_RECORD,
        {"body": "one", "record_id": "rec-1"},
        agent_version=DEMO_AGENT_VERSION,
        idempotency_key="k1",
    )
    second = demo.registry.invoke_tool(
        PUT_RECORD,
        {"body": "two", "record_id": "rec-1"},
        agent_version=DEMO_AGENT_VERSION,
        idempotency_key="k2",
    )
    assert first.output is not None
    assert second.output is not None
    assert first.output["created"] is True
    assert second.output["created"] is False
    assert second.replayed is False
    assert demo.executions == 2
    assert len(demo.store) == 1
    stored = demo.store.get("rec-1")
    assert stored is not None
    assert stored["body"] == "one"


def test_double_invoke_evidence_omits_the_payload(tmp_path: Path) -> None:
    token = "token-should-not-leak"
    path = write_double_invoke_evidence(tmp_path, body=token)
    text = path.read_text(encoding="utf-8")
    payload = json.loads(text)
    assert token not in text
    assert payload["eval"] == "tools.double-invoke"
    assert payload["author_check"] == "PASS"
    assert payload["executions"] == 1
    assert payload["store_rows"] == 1
    assert payload["second_replayed"] is True
    assert payload["first_replayed"] is False

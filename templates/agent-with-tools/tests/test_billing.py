"""Registry, allowlist, idempotency, and the Lambda handler contract."""

import json

from agent_with_tools.billing import (
    FETCH_INVOICE,
    SUBMIT_INVOICE_NOTE,
    TARGET_NAME,
    BillingDesk,
)
from agent_with_tools.version import AGENT_VERSION
from agentcore_tools import LambdaContext, gateway_tool_name, make_lambda_handler


def _read(desk: BillingDesk, *, tenant_id: str = "acme", invoice_id: str = "INV-1001", version: str = AGENT_VERSION):
    return desk.registry.invoke_tool(
        FETCH_INVOICE,
        {"invoice_id": invoice_id, "tenant_id": tenant_id, "user_id": "user-1"},
        agent_version=version,
        actor_id="user-1",
        runtime_session_id="session-1",
    )


def _note(
    desk: BillingDesk,
    *,
    key: str = "note-1",
    note: str = "customer requested a copy",
    invoice_id: str = "INV-1001",
    tenant_id: str = "acme",
):
    return desk.registry.invoke_tool(
        SUBMIT_INVOICE_NOTE,
        {
            "idempotency_key": key,
            "invoice_id": invoice_id,
            "note": note,
            "tenant_id": tenant_id,
            "user_id": "user-1",
        },
        agent_version=AGENT_VERSION,
        idempotency_key=key,
        actor_id="user-1",
        runtime_session_id="session-1",
    )


def test_allowlist_reads_the_caller_tenant() -> None:
    desk = BillingDesk()
    acme = _read(desk)
    globex = _read(desk, tenant_id="globex")
    assert acme.ok and acme.output is not None
    assert globex.ok and globex.output is not None
    assert acme.output["amount"] == "1250.00"
    assert globex.output["amount"] == "9999.00"
    assert desk.call_count(FETCH_INVOICE) == 2


def test_unpermitted_version_does_not_run_the_handler() -> None:
    desk = BillingDesk()
    denied = _read(desk, version="0.9.0")
    assert denied.error is not None
    assert denied.error.code == "policy_denied"
    assert desk.call_count(FETCH_INVOICE) == 0


def test_forbid_wins_over_permit() -> None:
    desk = BillingDesk()
    desk.policy.forbid(AGENT_VERSION, FETCH_INVOICE)
    denied = _read(desk)
    assert denied.error is not None
    assert denied.error.code == "policy_denied"
    assert desk.call_count(FETCH_INVOICE) == 0


def test_side_effect_replays_one_note() -> None:
    desk = BillingDesk()
    first = _note(desk)
    second = _note(desk)
    assert first.ok and first.output is not None
    assert first.output["duplicate"] is False
    assert second.replayed
    assert desk.call_count(SUBMIT_INVOICE_NOTE) == 1
    assert desk.note_count("acme", "INV-1001") == 1


def test_same_key_with_different_note_is_fatal() -> None:
    desk = BillingDesk()
    assert _note(desk).ok
    conflict = _note(desk, note="a different note")
    assert conflict.error is not None
    assert conflict.error.code == "idempotency_conflict"
    assert desk.note_count("acme", "INV-1001") == 1
    assert desk.call_count(SUBMIT_INVOICE_NOTE) == 1


def test_missing_invoice_is_fatal_and_retryable_read_is_not_cached() -> None:
    desk = BillingDesk()
    missing = _read(desk, invoice_id="INV-4040")
    assert missing.error is not None
    assert missing.error.error_class.value == "fatal"
    assert missing.error.code == "invoice_not_found"
    desk.fail_next_fetch()
    retryable = _read(desk, invoice_id="INV-1001")
    assert retryable.error is not None
    assert retryable.error.error_class.value == "retryable"
    assert retryable.error.code == "billing_unavailable"
    recovered = _read(desk, invoice_id="INV-1001")
    assert recovered.ok
    assert desk.call_count(FETCH_INVOICE) == 3


def test_schema_rejects_unknown_fields_without_running_the_handler() -> None:
    desk = BillingDesk()
    rejected = desk.registry.invoke_tool(
        FETCH_INVOICE,
        {"invoice_id": "INV-1001", "tenant_id": "acme", "user_id": "user-1", "extra": "no"},
        agent_version=AGENT_VERSION,
        actor_id="user-1",
        runtime_session_id="session-1",
    )
    assert rejected.error is not None
    assert rejected.error.code == "schema_rejected"
    assert desk.call_count(FETCH_INVOICE) == 0


def test_write_requires_an_idempotency_key() -> None:
    desk = BillingDesk()
    missing = desk.registry.invoke_tool(
        SUBMIT_INVOICE_NOTE,
        {
            "idempotency_key": "note-1",
            "invoice_id": "INV-1001",
            "note": "hello",
            "tenant_id": "acme",
            "user_id": "user-1",
        },
        agent_version=AGENT_VERSION,
        actor_id="user-1",
        runtime_session_id="session-1",
    )
    assert missing.error is not None
    assert missing.error.code == "idempotency_key_required"
    assert desk.call_count(SUBMIT_INVOICE_NOTE) == 0


def test_cedar_allowlist_names_the_gateway_actions() -> None:
    desk = BillingDesk()
    binding = desk.registry.binding
    assert binding is not None
    target = binding.target(TARGET_NAME)
    actions = {name: target.visible_name(name) for name in target.tool_names}
    statements = desk.policy.cedar_statements(
        agent_version=AGENT_VERSION,
        gateway_resource="gateway-dev",
        actions=actions,
    )
    text = "\n".join(statements)
    assert "billing___fetch_invoice" in text
    assert "billing___submit_invoice_note" in text
    assert text.count("permit(") == 2
    assert "forbid(" not in text
    empty = desk.policy.cedar_statements(agent_version="0.9.0", gateway_resource="gateway-dev", actions=actions)
    assert empty == ()


def test_lambda_put_if_absent_survives_a_second_delivery() -> None:
    desk = BillingDesk()
    visible = gateway_tool_name(TARGET_NAME, SUBMIT_INVOICE_NOTE)
    event = {
        "idempotency_key": "note-9",
        "invoice_id": "INV-1002",
        "note": "paid copy",
        "tenant_id": "acme",
        "user_id": "user-1",
    }
    context = LambdaContext(
        tool_name=visible,
        gateway_id=desk.gateway_id,
        target_id="target-local",
        request_id="req-1",
    )
    handler = make_lambda_handler(desk.registry, agent_version=AGENT_VERSION)
    first = handler(event, context)
    second = handler(event, context)
    assert first.get("isError") is not True
    body = json.loads(first["content"][0]["text"])
    again = json.loads(second["content"][0]["text"])
    assert body["duplicate"] is False
    assert again["duplicate"] is True
    assert desk.note_count("acme", "INV-1002") == 1
    assert desk.call_count(SUBMIT_INVOICE_NOTE) == 2

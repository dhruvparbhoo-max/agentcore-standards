"""Checkpointer label, prompt rejection, and approval parsing."""

import pytest
from agentcore_langchain import (
    OFFLINE_CHECKPOINTER,
    build_checkpointer,
    parse_approval,
    reject_non_string_prompt,
)
from agentcore_langchain.hitl import agent_middleware


def test_offline_checkpointer_is_labeled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTCORE_MEMORY_ID", raising=False)
    choice = build_checkpointer()
    assert choice.kind == OFFLINE_CHECKPOINTER


def test_memory_id_without_region_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTCORE_MEMORY_ID", "memory-local")
    monkeypatch.delenv("AWS_REGION", raising=False)
    with pytest.raises(RuntimeError, match="AWS_REGION"):
        build_checkpointer()


def test_non_string_prompt_is_rejected_before_the_graph() -> None:
    rejected = reject_non_string_prompt({"prompt": [{"type": "toolUse"}]})
    assert rejected is not None
    assert rejected["status"] == "rejected"
    assert reject_non_string_prompt({"prompt": "  "}) is not None
    assert reject_non_string_prompt({"prompt": "Fetch invoice INV-1001."}) is None
    assert reject_non_string_prompt({"decision": "approve"}) is None
    assert reject_non_string_prompt({"prompt": "  ", "decision": "approve"}) is None


def test_edit_and_respond_are_not_approvals() -> None:
    with pytest.raises(ValueError, match="approve or reject"):
        parse_approval("edit", reject_message="The note was not filed.")
    with pytest.raises(ValueError, match="approve or reject"):
        parse_approval({"type": "respond", "message": "done"}, reject_message="The note was not filed.")
    assert parse_approval(None, reject_message="The note was not filed.") is None
    assert parse_approval("approve", reject_message="The note was not filed.") == {"type": "approve"}
    rejected = parse_approval("reject", reject_message="The note was not filed.")
    assert rejected == {"message": "The note was not filed.", "type": "reject"}


def test_approval_is_the_outer_gate() -> None:
    stack = agent_middleware(
        read_tools=("fetch_invoice",),
        write_tools={"submit_invoice_note": "Filing an invoice note writes to the billing record."},
    )
    hitl = stack[0]
    assert "fetch_invoice" not in hitl.interrupt_on
    write = hitl.interrupt_on["submit_invoice_note"]
    assert write["allowed_decisions"] == ["approve", "reject"]
    assert "edit" not in write["allowed_decisions"]
    assert "respond" not in write["allowed_decisions"]

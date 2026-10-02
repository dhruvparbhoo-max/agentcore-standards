"""Offline eval pack: goldens, guardrails, groundedness, and HITL on one harness."""

import json
from pathlib import Path

from agentcore_eval import VerdictStatus, load_golden_dataset, pack_suite_dir, run_suite
from agentcore_eval.stub_agent import business_harness

_REQUIRED = {
    "approve.blocked-without-approval",
    "approve.expires",
    "approve.proceeds-with-approval",
    "crm.lookup-account",
    "crm.write-note-denied",
    "groundedness.invoice-abstain",
    "groundedness.invoice-balance-invented",
    "groundedness.invoice-balance-supported",
    "groundedness.invoice-status-contradicted",
    "guardrail.allow.balance-sentence",
    "guardrail.allow.guarded-memory",
    "guardrail.allow.invoice-question",
    "guardrail.block.prompt-injection",
    "guardrail.block.raw-memory",
    "guardrail.block.synthetic-marker",
    "hitl.blocked-without-approval",
    "hitl.expired",
    "hitl.proceeds-with-approval",
    "invoice.lookup-missing",
    "invoice.lookup-open",
    "invoice.record-payment-idempotent",
    "invoice.then-crm",
}


def test_pack_passes_on_the_in_memory_harness(tmp_path: Path) -> None:
    dataset = load_golden_dataset()
    assert 5 <= len(dataset.scenarios) <= 10
    report = run_suite(
        pack_suite_dir(),
        harness_factory=business_harness,
        agent_version="0.1.0",
        evidence_dir=tmp_path,
    )
    names = {item.eval_name for item in report.verdicts}
    assert names == _REQUIRED
    assert report.ok
    assert {item.status for item in report.verdicts} == {VerdictStatus.PASS}
    marker = "arn:" + "aws:"
    for verdict in report.verdicts:
        assert verdict.evidence_path is not None
        text = verdict.evidence_path.read_text(encoding="utf-8")
        assert marker not in text
        body = json.loads(text)
        assert body["status"] == "PASS"
        assert body["eval"] == verdict.eval_name

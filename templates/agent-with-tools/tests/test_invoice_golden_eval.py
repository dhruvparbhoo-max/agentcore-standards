"""Offline graders on the in-memory harness, and the runtime smoke skip."""

from pathlib import Path

import pytest
from agent_with_tools.agent import build_agent
from agent_with_tools.entrypoint import set_agent_factory
from agent_with_tools.harness import AgentWithToolsHarness
from agent_with_tools.scripted import ScriptedInvoiceModel
from agent_with_tools.version import AGENT_VERSION
from agentcore_eval import VerdictStatus, missing_runtime_settings, run_suite

_OFFLINE = Path(__file__).resolve().parents[1] / "evals" / "offline"
_RUNTIME = Path(__file__).resolve().parents[1] / "evals" / "runtime"


def test_offline_graders_pass(tmp_path: Path) -> None:
    set_agent_factory(lambda: build_agent(ScriptedInvoiceModel()))
    report = run_suite(
        _OFFLINE,
        harness_factory=AgentWithToolsHarness,
        agent_version=AGENT_VERSION,
        evidence_dir=tmp_path,
    )
    assert report.ok
    names = [verdict.eval_name for verdict in report.verdicts]
    assert names == [
        "agent-with-tools.invoice-read",
        "agent-with-tools.invoice-note",
        "agent-with-tools.policy-deny",
        "agent-with-tools.fatal-read",
        "agent-with-tools.retry-read",
    ]
    assert all(verdict.status is VerdictStatus.PASS for verdict in report.verdicts)
    assert all(verdict.evidence_path is not None and verdict.evidence_path.exists() for verdict in report.verdicts)


@pytest.mark.runtime
@pytest.mark.skipif(
    bool(missing_runtime_settings()),
    reason="Set AWS_ACCESS_KEY_ID, AWS_REGION, AGENTCORE_RUNTIME_ARN, and AGENTCORE_SPAN_LOG_GROUP",
)
def test_runtime_smoke_when_configured(tmp_path: Path) -> None:
    report = run_suite(
        _RUNTIME,
        harness_factory=AgentWithToolsHarness.for_agentcore_runtime,
        agent_version=AGENT_VERSION,
        evidence_dir=tmp_path,
    )
    assert report.ok
    assert report.verdicts[0].eval_name == "agent-with-tools.runtime-smoke"
    assert report.verdicts[0].status in {VerdictStatus.PASS, VerdictStatus.PASS_NOTES}

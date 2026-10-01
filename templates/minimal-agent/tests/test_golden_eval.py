"""Golden eval: in-memory by default, real AgentCore Runtime when configured."""

from pathlib import Path

import pytest
from agentcore_eval import VerdictStatus, missing_runtime_settings, run_suite
from minimal_agent import AGENT_VERSION, MinimalAgentHarness

_EVALS = Path(__file__).resolve().parents[1] / "evals"
_RUNTIME = pytest.mark.runtime
_MISSING_RUNTIME = bool(missing_runtime_settings())


def test_golden_turn_on_in_memory_harness(tmp_path: Path) -> None:
    report = run_suite(
        _EVALS,
        harness_factory=MinimalAgentHarness,
        agent_version=AGENT_VERSION,
        evidence_dir=tmp_path,
    )
    assert report.ok
    verdict = report.verdicts[0]
    assert verdict.status is VerdictStatus.PASS
    assert verdict.eval_name == "minimal-agent.golden-turn"
    assert verdict.evidence_path is not None
    assert verdict.evidence_path.exists()


@_RUNTIME
@pytest.mark.skipif(
    _MISSING_RUNTIME,
    reason="Set AWS_ACCESS_KEY_ID, AWS_REGION, AGENTCORE_RUNTIME_ARN, and AGENTCORE_SPAN_LOG_GROUP",
)
def test_golden_turn_on_agentcore_runtime(tmp_path: Path) -> None:
    report = run_suite(
        _EVALS,
        harness_factory=MinimalAgentHarness.for_agentcore_runtime,
        agent_version=AGENT_VERSION,
        evidence_dir=tmp_path,
    )
    assert report.ok
    assert report.verdicts[0].status in {VerdictStatus.PASS, VerdictStatus.PASS_NOTES}

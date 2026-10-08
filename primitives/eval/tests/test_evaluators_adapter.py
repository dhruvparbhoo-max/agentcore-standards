"""Optional Evaluators adapter. The real runner is not called in this module's default tests."""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from agentcore_eval import (
    DEFAULT_EVALUATOR_IDS,
    EvaluatorsConfigError,
    HarnessAgentInvoker,
    InMemoryRuntimeHarness,
    OnDemandEvaluatorsAdapter,
    VerdictStatus,
    load_golden_dataset,
    pack_suite_dir,
    run_suite,
)
from agentcore_eval.stub_agent import business_harness
from bedrock_agentcore.evaluation import AgentInvokerInput


def _runtime_settings_present() -> bool:
    names = ("AWS_ACCESS_KEY_ID", "AWS_REGION", "AGENTCORE_RUNTIME_ARN", "AGENTCORE_SPAN_LOG_GROUP")
    return all(os.environ.get(name) for name in names)


_CREATED: list[Any] = []


class _Runner:
    def __init__(self, *, region: str) -> None:
        self.region = region
        self.calls: list[dict[str, Any]] = []
        self.output: Any = None
        _CREATED.append(self)

    def run(self, **kwargs: Any) -> dict[str, str]:
        self.calls.append(kwargs)
        dataset = kwargs["dataset"]
        scenario = dataset.scenarios[0]
        turn = scenario.turns[0]
        self.output = kwargs["agent_invoker"](
            AgentInvokerInput(payload=turn.input, session_id="scenario-session-" + ("a" * 24))
        )
        return {"status": "stub"}


def test_from_env_requires_region_and_log_group(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AGENTCORE_SPAN_LOG_GROUP", raising=False)
    with pytest.raises(EvaluatorsConfigError):
        OnDemandEvaluatorsAdapter.from_env()


def test_adapter_calls_injected_runner_and_leaves_outcome_checks_in_place(tmp_path: Path) -> None:
    _CREATED.clear()
    report = run_suite(
        pack_suite_dir(),
        harness_factory=business_harness,
        agent_version="0.1.0",
        evidence_dir=tmp_path,
    )
    assert report.ok
    assert report.verdicts[0].status is VerdictStatus.PASS

    dataset = load_golden_dataset()
    adapter = OnDemandEvaluatorsAdapter(region="us-east-1", log_group="spans-local")
    result = adapter.run_with_harness(
        dataset=dataset,
        harness=business_harness(),
        actor_id="actor-ap-clerk",
        agent_version="0.1.0",
        runner_type=_Runner,
        span_collector=object(),
    )
    assert result == {"status": "stub"}
    runner = _CREATED[-1]
    assert runner.region == "us-east-1"
    call = runner.calls[0]
    assert [item.scenario_id for item in call["dataset"].scenarios] == [item.scenario_id for item in dataset.scenarios]
    assert call["config"].evaluator_config.evaluator_ids == list(DEFAULT_EVALUATOR_IDS)
    assert call["config"].evaluation_delay_seconds == 180
    assert "outcomes" in call["dataset"].scenarios[0].metadata
    assert runner.output.agent_output["result"] == dataset.scenarios[0].turns[0].expected_response
    assert report.ok


def test_string_payload_reaches_the_harness() -> None:
    def handler(
        payload: Mapping[str, Any],
        *,
        session_id: str,
        actor_id: str,
        agent_version: str,
    ) -> Mapping[str, Any]:
        del session_id, actor_id, agent_version
        return {"echo": payload["prompt"]}

    invoker = HarnessAgentInvoker(InMemoryRuntimeHarness(handler), actor_id="actor-a", agent_version="0.1.0")
    output = invoker(AgentInvokerInput(payload="ping", session_id="scenario-session-" + ("b" * 24)))
    assert output.agent_output["echo"] == "ping"
    invoker.close()


@pytest.mark.runtime
@pytest.mark.skipif(not _runtime_settings_present(), reason="AWS runtime settings are unset")
def test_real_runner_constructs_when_runtime_settings_exist() -> None:
    adapter = OnDemandEvaluatorsAdapter.from_env()
    runner = adapter.create_runner()
    assert runner.__class__.__name__ == "OnDemandEvaluationDatasetRunner"

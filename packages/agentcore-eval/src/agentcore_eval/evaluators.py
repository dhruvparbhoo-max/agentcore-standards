"""Optional AgentCore Evaluators adapter.

``OnDemandEvaluatorsAdapter.run`` builds an SDK dataset from a golden file and
calls ``OnDemandEvaluationDatasetRunner.run``. The return value is the SDK
``EvaluationResult``. It is not a ``Verdict``. Ship gates stay on
``run_eval`` / ``run_suite``, which compare harness outcomes to the dataset.

Constructing the real runner creates AWS clients. Tests pass ``runner_type``
so the default suite never calls Evaluate or CloudWatch.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from bedrock_agentcore.evaluation import (
    CloudWatchAgentSpanCollector,
    Dataset,
    EvaluationRunConfig,
    EvaluatorConfig,
    PredefinedScenario,
    Turn,
)

from agentcore_eval.dataset_adapter import HarnessAgentInvoker, load_on_demand_runner
from agentcore_eval.golden import GoldenDataset, GoldenScenario, GoldenTurn
from agentcore_eval.harness import RuntimeConfigError, RuntimeHarness

DEFAULT_EVALUATOR_IDS = (
    "Builtin.Correctness",
    "Builtin.GoalSuccessRate",
    "Builtin.TrajectoryExactOrderMatch",
    "Builtin.Faithfulness",
)


class EvaluatorsConfigError(RuntimeConfigError):
    """AWS settings for the optional Evaluators layer are missing."""


class OnDemandEvaluatorsAdapter:
    """Call the on-demand dataset runner when an operator asks for it."""

    def __init__(
        self,
        *,
        region: str,
        log_group: str,
        evaluator_ids: tuple[str, ...] = DEFAULT_EVALUATOR_IDS,
        evaluation_delay_seconds: int = 180,
        max_concurrent_scenarios: int = 5,
    ) -> None:
        if not region.strip():
            raise EvaluatorsConfigError("AWS_REGION is required to call AgentCore Evaluators")
        if not log_group.strip():
            raise EvaluatorsConfigError("AGENTCORE_SPAN_LOG_GROUP is required to call AgentCore Evaluators")
        if not evaluator_ids or any(not item.strip() for item in evaluator_ids):
            raise EvaluatorsConfigError("at least one evaluator id is required")
        if evaluation_delay_seconds < 0:
            raise EvaluatorsConfigError("evaluation_delay_seconds must be >= 0")
        if max_concurrent_scenarios < 1:
            raise EvaluatorsConfigError("max_concurrent_scenarios must be >= 1")
        self._region = region.strip()
        self._log_group = log_group.strip()
        self._evaluator_ids = evaluator_ids
        self._evaluation_delay_seconds = evaluation_delay_seconds
        self._max_concurrent_scenarios = max_concurrent_scenarios

    @classmethod
    def from_env(cls) -> OnDemandEvaluatorsAdapter:
        """Read region and span log group. Raises when either name is unset."""
        region = os.environ.get("AWS_REGION", "").strip()
        log_group = os.environ.get("AGENTCORE_SPAN_LOG_GROUP", "").strip()
        if not region or not log_group:
            raise EvaluatorsConfigError("Set AWS_REGION and AGENTCORE_SPAN_LOG_GROUP to call AgentCore Evaluators")
        return cls(region=region, log_group=log_group)

    def create_runner(self, runner_type: Callable[..., Any] | None = None) -> Any:
        """Build the runner. The default type is the SDK class, which opens AWS clients."""
        factory = load_on_demand_runner() if runner_type is None else runner_type
        return factory(region=self._region)

    def run(
        self,
        *,
        dataset: GoldenDataset,
        agent_invoker: Callable[..., Any],
        runner_type: Callable[..., Any] | None = None,
        span_collector: Any | None = None,
    ) -> Any:
        """Invoke the runner. The result is not a ship verdict."""
        collector = span_collector
        if collector is None:
            collector = CloudWatchAgentSpanCollector(log_group_name=self._log_group, region=self._region)
        runner = self.create_runner(runner_type)
        return runner.run(
            config=self._config(),
            dataset=to_sdk_dataset(dataset),
            agent_invoker=agent_invoker,
            span_collector=collector,
        )

    def run_with_harness(
        self,
        *,
        dataset: GoldenDataset,
        harness: RuntimeHarness,
        actor_id: str,
        agent_version: str,
        runner_type: Callable[..., Any] | None = None,
        span_collector: Any | None = None,
    ) -> Any:
        """Run evaluators through ``HarnessAgentInvoker`` so turns stay on the harness."""
        invoker = HarnessAgentInvoker(harness, actor_id=actor_id, agent_version=agent_version)
        try:
            return self.run(
                dataset=dataset,
                agent_invoker=invoker,
                runner_type=runner_type,
                span_collector=span_collector,
            )
        finally:
            invoker.close()

    def _config(self) -> EvaluationRunConfig:
        return EvaluationRunConfig(
            evaluator_config=EvaluatorConfig(evaluator_ids=list(self._evaluator_ids)),
            evaluation_delay_seconds=self._evaluation_delay_seconds,
            max_concurrent_scenarios=self._max_concurrent_scenarios,
        )


def to_sdk_dataset(dataset: GoldenDataset) -> Dataset:
    """Project a golden dataset onto the SDK predefined scenario types.

    Outcome expectations stay in scenario metadata. Evaluators that understand
    ``expected_response``, ``assertions``, and ``expected_trajectory`` receive
    those fields. They do not receive a ``Verdict``.
    """
    return Dataset(scenarios=[_scenario(scenario) for scenario in dataset.scenarios])


def _scenario(scenario: GoldenScenario) -> PredefinedScenario:
    return PredefinedScenario(
        scenario_id=scenario.scenario_id,
        turns=[_turn(turn) for turn in scenario.turns],
        expected_trajectory=list(scenario.expected_trajectory),
        assertions=list(scenario.assertions),
        metadata={
            "actor_id": scenario.actor_id,
            "outcomes": [_outcome(turn) for turn in scenario.turns],
            "shelf": scenario.shelf,
        },
    )


def _turn(turn: GoldenTurn) -> Turn:
    return Turn(input=turn.input, expected_response=turn.expected_response)


def _outcome(turn: GoldenTurn) -> dict[str, Any]:
    outcome = turn.outcome
    return {
        "balance": outcome.balance,
        "replayed": outcome.replayed,
        "result_excludes": list(outcome.result_excludes),
        "status": outcome.status,
        "tool_calls": list(outcome.tool_calls),
    }

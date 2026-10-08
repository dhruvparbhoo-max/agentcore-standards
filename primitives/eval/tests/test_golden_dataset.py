"""Golden dataset validation and fail-closed outcome checks."""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest
from agentcore_eval import (
    InMemoryRuntimeHarness,
    VerdictStatus,
    dataset_evals,
    load_golden_dataset,
    run_eval,
)
from agentcore_eval.golden import parse_golden_dataset


def test_business_dataset_matches_trajectories() -> None:
    dataset = load_golden_dataset()
    assert dataset.suite == "business"
    ids = [scenario.scenario_id for scenario in dataset.scenarios]
    assert len(ids) == len(set(ids))
    for scenario in dataset.scenarios:
        flat = tuple(call for turn in scenario.turns for call in turn.outcome.tool_calls)
        assert flat == scenario.expected_trajectory
        assert scenario.assertions
        assert scenario.actor_id.startswith("actor-")


def test_duplicate_scenario_id_is_rejected() -> None:
    dataset = load_golden_dataset()
    payload = _document(dataset)
    payload["scenarios"].append(payload["scenarios"][0])
    with pytest.raises(ValueError, match="duplicate scenario_id"):
        parse_golden_dataset(payload)


def test_outcome_check_fails_when_the_handler_disagrees(tmp_path: Path) -> None:
    def handler(
        payload: Mapping[str, Any],
        *,
        session_id: str,
        actor_id: str,
        agent_version: str,
    ) -> Mapping[str, Any]:
        del payload, session_id, actor_id, agent_version
        return {"status": "ok", "result": "nope", "tool_calls": [], "replayed": False, "balance": None}

    evaluation = dataset_evals(load_golden_dataset())[0]
    verdict = run_eval(
        evaluation,
        agent_version="0.1.0",
        harness=InMemoryRuntimeHarness(handler),
        evidence_dir=tmp_path,
    )
    assert verdict.status is VerdictStatus.FAIL
    assert verdict.evidence_path is not None


def _document(dataset: Any) -> dict[str, Any]:
    return {
        "schema_version": dataset.schema_version,
        "suite": dataset.suite,
        "scenarios": [
            {
                "scenario_id": scenario.scenario_id,
                "turns": [
                    {
                        "input": turn.input,
                        "expected_response": turn.expected_response,
                    }
                    for turn in scenario.turns
                ],
                "expected_trajectory": list(scenario.expected_trajectory),
                "assertions": list(scenario.assertions),
                "metadata": {
                    "actor_id": scenario.actor_id,
                    "shelf": scenario.shelf,
                    "outcomes": [
                        {
                            "status": turn.outcome.status,
                            "tool_calls": list(turn.outcome.tool_calls),
                            "replayed": turn.outcome.replayed,
                            "balance": turn.outcome.balance,
                            "result_excludes": list(turn.outcome.result_excludes),
                        }
                        for turn in scenario.turns
                    ],
                },
            }
            for scenario in dataset.scenarios
        ],
    }

"""A pattern's ``eval/golden_set.json``: shape check and an offline score.

The shape follows the AgentCore predefined scenario fields (``scenario_id``,
``turns``, ``expected_trajectory``, ``assertions``, ``metadata``), the same as
``agentcore_eval.golden``. The outcome per turn says what the session must
return: a status, the tools called, text it must contain or must not contain,
and for retrieval patterns the sources it must cite.

The offline score runs the scripted model through ``AgentSession``. It proves
the wiring, not the model. The ship score comes from the Runtime eval.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from agentcore_agent.build import AgentSession

GOLDEN_SCHEMA_VERSION = "agentcore-standards.pattern-golden.v1"

_STRINGS = {"type": "array", "items": {"type": "string", "minLength": 1}}
GOLDEN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["schema_version", "pattern", "scenarios"],
    "properties": {
        "schema_version": {"const": GOLDEN_SCHEMA_VERSION},
        "pattern": {"type": "string", "minLength": 1},
        "scenarios": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["scenario_id", "turns", "expected_trajectory", "assertions", "metadata"],
                "properties": {
                    "scenario_id": {"type": "string", "pattern": r"^[a-z0-9][a-z0-9._-]*$"},
                    "turns": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["input", "expected_response"],
                            "properties": {
                                "input": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["prompt"],
                                    "properties": {"prompt": {"type": "string", "minLength": 1}},
                                },
                                "expected_response": {"type": "string"},
                            },
                        },
                    },
                    "expected_trajectory": _STRINGS,
                    "assertions": {**_STRINGS, "minItems": 1},
                    "metadata": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["actor_id", "tags", "outcomes"],
                        "properties": {
                            "actor_id": {"type": "string", "minLength": 1},
                            "tags": _STRINGS,
                            "outcomes": {
                                "type": "array",
                                "minItems": 1,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "required": ["status"],
                                    "properties": {
                                        "status": {"enum": ["completed", "paused", "blocked"]},
                                        "tools_called": _STRINGS,
                                        "contains": _STRINGS,
                                        "excludes": _STRINGS,
                                        "sources": _STRINGS,
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
    },
}


@dataclass(frozen=True)
class CaseScore:
    scenario_id: str
    passed: bool
    problems: tuple[str, ...]


@dataclass(frozen=True)
class GoldenScore:
    cases: tuple[CaseScore, ...]

    @property
    def score(self) -> float:
        return sum(case.passed for case in self.cases) / len(self.cases) if self.cases else 0.0


def load_golden(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: must be a JSON object")
    return raw


def golden_problems(raw: Any, *, pattern: str | None = None) -> list[str]:
    """Every shape problem, plus one outcome per turn and a matching pattern name."""
    validator = Draft202012Validator(GOLDEN_SCHEMA)
    problems = [
        f"{'.'.join(str(p) for p in error.absolute_path) or '(top level)'}: {error.message}"
        for error in validator.iter_errors(raw)
    ]
    if problems:
        return problems
    if pattern is not None and raw["pattern"] != pattern:
        problems.append(f"pattern: must be {pattern!r}")
    seen: set[str] = set()
    for scenario in raw["scenarios"]:
        sid = scenario["scenario_id"]
        if sid in seen:
            problems.append(f"scenarios: duplicate scenario_id {sid}")
        seen.add(sid)
        if len(scenario["metadata"]["outcomes"]) != len(scenario["turns"]):
            problems.append(f"{sid}: one outcome per turn")
    return problems


def score_golden(
    raw: Mapping[str, Any],
    session: AgentSession,
    *,
    session_id_for: Callable[[str, int], str],
    runs_per_case: int = 1,
) -> GoldenScore:
    """Run each scenario ``runs_per_case`` times. A case passes only when every run passes."""
    cases: list[CaseScore] = []
    for scenario in raw["scenarios"]:
        problems: list[str] = []
        for run in range(runs_per_case):
            problems.extend(_run_once(scenario, session, session_id_for(scenario["scenario_id"], run)))
        cases.append(CaseScore(scenario["scenario_id"], not problems, tuple(dict.fromkeys(problems))))
    return GoldenScore(tuple(cases))


def _run_once(scenario: Mapping[str, Any], session: AgentSession, session_id: str) -> list[str]:
    actor = scenario["metadata"]["actor_id"]
    problems: list[str] = []
    for turn, outcome in zip(scenario["turns"], scenario["metadata"]["outcomes"], strict=True):
        result = session.run(turn["input"]["prompt"], session_id=session_id, actor_id=actor)
        problems.extend(_compare(outcome, result.status, result.text, result.tools_called))
    return problems


def _compare(outcome: Mapping[str, Any], status: str, text: str, tools: Sequence[str]) -> list[str]:
    problems: list[str] = []
    if status != outcome["status"]:
        problems.append(f"status {status} != {outcome['status']}")
    if "tools_called" in outcome and list(tools) != list(outcome["tools_called"]):
        problems.append(f"tools {list(tools)} != {outcome['tools_called']}")
    for needle in outcome.get("contains", ()):
        if needle not in text:
            problems.append(f"missing {needle!r}")
    for needle in outcome.get("excludes", ()):
        if needle in text:
            problems.append(f"must not contain {needle!r}")
    for source in outcome.get("sources", ()):
        if source not in text:
            problems.append(f"does not cite {source!r}")
    return problems

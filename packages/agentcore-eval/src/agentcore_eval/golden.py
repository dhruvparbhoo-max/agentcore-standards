"""Golden datasets and the outcome checks that run them on a RuntimeHarness.

The JSON shape matches the AgentCore predefined scenario schema
(``scenario_id``, ``turns``, ``expected_trajectory``, ``assertions``, ``metadata``).
Outcome expectations live in ``metadata.outcomes``, one object per turn. Those
checks are the ship gate. The optional Evaluators adapter reads the same file
and does not replace them.
"""

from collections.abc import Mapping
from typing import Any

from agentcore_eval.dataset_adapter import payload_from_turn_input
from agentcore_eval.datasets import read_json
from agentcore_eval.harness import RuntimeHarness
from agentcore_eval.model import Eval, EvalContext

GOLDEN_SCHEMA = "agentcore-standards.golden.v1"
_SHELVES = frozenset({"tools", "hitl"})
_SCENARIO_KEYS = frozenset({"scenario_id", "turns", "expected_trajectory", "assertions", "metadata"})
_TURN_KEYS = frozenset({"input", "expected_response"})
_INPUT_KEYS = frozenset({"prompt", "tool", "args"})
_METADATA_KEYS = frozenset({"actor_id", "shelf", "outcomes"})
_OUTCOME_KEYS = frozenset({"status", "tool_calls", "replayed", "balance", "result_excludes"})
_TOP_KEYS = frozenset({"schema_version", "suite", "scenarios"})


class TurnOutcome:
    """Observable fields one turn must return."""

    def __init__(
        self,
        *,
        status: str,
        tool_calls: tuple[str, ...],
        replayed: bool,
        balance: str | None,
        result_excludes: tuple[str, ...],
    ) -> None:
        self.status = status
        self.tool_calls = tool_calls
        self.replayed = replayed
        self.balance = balance
        self.result_excludes = result_excludes


class GoldenTurn:
    """One authored turn plus the outcome the harness must observe."""

    def __init__(self, *, turn_input: str | dict[str, Any], expected_response: str, outcome: TurnOutcome) -> None:
        self.input = turn_input
        self.expected_response = expected_response
        self.outcome = outcome


class GoldenScenario:
    """One conversation. ``scenario_id`` is also the eval name."""

    def __init__(
        self,
        *,
        scenario_id: str,
        turns: tuple[GoldenTurn, ...],
        expected_trajectory: tuple[str, ...],
        assertions: tuple[str, ...],
        actor_id: str,
        shelf: str,
    ) -> None:
        self.scenario_id = scenario_id
        self.turns = turns
        self.expected_trajectory = expected_trajectory
        self.assertions = assertions
        self.actor_id = actor_id
        self.shelf = shelf


class GoldenDataset:
    """A named suite of predefined scenarios."""

    def __init__(self, *, schema_version: str, suite: str, scenarios: tuple[GoldenScenario, ...]) -> None:
        self.schema_version = schema_version
        self.suite = suite
        self.scenarios = scenarios


def load_golden_dataset(name: str = "business.json") -> GoldenDataset:
    """Load a packaged golden dataset."""
    return parse_golden_dataset(read_json(name))


def parse_golden_dataset(payload: Mapping[str, Any]) -> GoldenDataset:
    """Validate ``payload`` and return the dataset. Unknown keys are errors."""
    _reject_unknown(payload, _TOP_KEYS, label="dataset")
    schema_version = _require_str(payload.get("schema_version"), label="schema_version")
    if schema_version != GOLDEN_SCHEMA:
        raise ValueError(f"schema_version must be {GOLDEN_SCHEMA}")
    suite = _require_str(payload.get("suite"), label="suite")
    raw_scenarios = payload.get("scenarios")
    if not isinstance(raw_scenarios, list) or not raw_scenarios:
        raise ValueError("scenarios must be a non-empty list")
    scenarios: list[GoldenScenario] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_scenarios):
        scenario = _scenario(raw, label=f"scenarios[{index}]")
        if scenario.scenario_id in seen:
            raise ValueError(f"duplicate scenario_id {scenario.scenario_id}")
        seen.add(scenario.scenario_id)
        scenarios.append(scenario)
    return GoldenDataset(schema_version=schema_version, suite=suite, scenarios=tuple(scenarios))


def dataset_evals(dataset: GoldenDataset) -> tuple[Eval, ...]:
    """Build one ``Eval`` per scenario. The harness handler produces the outcome."""
    return tuple(_scenario_eval(scenario) for scenario in dataset.scenarios)


def _scenario_eval(scenario: GoldenScenario) -> Eval:
    def setup(harness: RuntimeHarness, ctx: EvalContext) -> None:
        ctx.actor_id = scenario.actor_id
        ctx.session = harness.start(actor_id=scenario.actor_id, agent_version=ctx.agent_version)

    def act(harness: RuntimeHarness, ctx: EvalContext) -> None:
        session = ctx.session
        if session is None:
            raise AssertionError("setup did not bind a session")
        for turn in scenario.turns:
            ctx.results.append(harness.invoke(session, payload_from_turn_input(turn.input)))

    def assert_(harness: RuntimeHarness, ctx: EvalContext) -> None:
        del harness
        _assert_scenario(scenario, ctx)

    return Eval(
        name=scenario.scenario_id,
        rubric=f"[{scenario.shelf}] " + " ".join(scenario.assertions),
        setup=setup,
        act=act,
        assert_=assert_,
    )


def _assert_scenario(scenario: GoldenScenario, ctx: EvalContext) -> None:
    if len(ctx.results) != len(scenario.turns):
        raise AssertionError(f"{scenario.scenario_id}: expected {len(scenario.turns)} turns, got {len(ctx.results)}")
    actual: list[str] = []
    for index, (turn, result) in enumerate(zip(scenario.turns, ctx.results, strict=True)):
        output = result.output
        label = f"{scenario.scenario_id} turn {index}"
        if output.get("result") != turn.expected_response:
            raise AssertionError(f"{label}: result {output.get('result')!r} != {turn.expected_response!r}")
        outcome = turn.outcome
        if output.get("status") != outcome.status:
            raise AssertionError(f"{label}: status {output.get('status')!r} != {outcome.status!r}")
        tool_calls = output.get("tool_calls")
        if not isinstance(tool_calls, list) or [str(item) for item in tool_calls] != list(outcome.tool_calls):
            raise AssertionError(f"{label}: tool_calls {tool_calls!r} != {list(outcome.tool_calls)!r}")
        if output.get("replayed") is not outcome.replayed:
            raise AssertionError(f"{label}: replayed {output.get('replayed')!r} != {outcome.replayed}")
        if output.get("balance") != outcome.balance:
            raise AssertionError(f"{label}: balance {output.get('balance')!r} != {outcome.balance!r}")
        text = output.get("result")
        result_text = text if isinstance(text, str) else ""
        for excluded in outcome.result_excludes:
            if excluded in result_text:
                raise AssertionError(f"{label}: result contains excluded text {excluded!r}")
        actual.extend(outcome.tool_calls)
    if tuple(actual) != scenario.expected_trajectory:
        raise AssertionError(f"{scenario.scenario_id}: trajectory {actual!r} != {list(scenario.expected_trajectory)!r}")


def _scenario(raw: object, *, label: str) -> GoldenScenario:
    body = _object(raw, label=label)
    _reject_unknown(body, _SCENARIO_KEYS, label=label)
    scenario_id = _require_str(body.get("scenario_id"), label=f"{label}.scenario_id")
    if any(char.isspace() for char in scenario_id):
        raise ValueError(f"{label}.scenario_id must not contain spaces")
    turns = _turns(body.get("turns"), label=f"{label}.turns")
    trajectory = _str_tuple(body.get("expected_trajectory"), label=f"{label}.expected_trajectory", allow_empty=True)
    assertions = _str_tuple(body.get("assertions"), label=f"{label}.assertions", allow_empty=False)
    metadata = _object(body.get("metadata"), label=f"{label}.metadata")
    _reject_unknown(metadata, _METADATA_KEYS, label=f"{label}.metadata")
    actor_id = _require_str(metadata.get("actor_id"), label=f"{label}.metadata.actor_id")
    shelf = _require_str(metadata.get("shelf"), label=f"{label}.metadata.shelf")
    if shelf not in _SHELVES:
        raise ValueError(f"{label}.metadata.shelf must be one of {sorted(_SHELVES)}")
    outcomes = _outcomes(metadata.get("outcomes"), label=f"{label}.metadata.outcomes")
    if len(outcomes) != len(turns):
        raise ValueError(f"{label}: outcomes and turns differ in length")
    paired = tuple(
        GoldenTurn(turn_input=turn[0], expected_response=turn[1], outcome=outcome)
        for turn, outcome in zip(turns, outcomes, strict=True)
    )
    flat = tuple(call for outcome in outcomes for call in outcome.tool_calls)
    if flat != trajectory:
        raise ValueError(f"{scenario_id}: expected_trajectory does not match outcome tool_calls")
    return GoldenScenario(
        scenario_id=scenario_id,
        turns=paired,
        expected_trajectory=trajectory,
        assertions=assertions,
        actor_id=actor_id,
        shelf=shelf,
    )


def _turns(raw: object, *, label: str) -> tuple[tuple[str | dict[str, Any], str], ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{label} must be a non-empty list")
    turns: list[tuple[str | dict[str, Any], str]] = []
    for index, item in enumerate(raw):
        body = _object(item, label=f"{label}[{index}]")
        _reject_unknown(body, _TURN_KEYS, label=f"{label}[{index}]")
        turns.append((_turn_input(body.get("input"), label=f"{label}[{index}].input"), _response(body, index, label)))
    return tuple(turns)


def _response(body: Mapping[str, Any], index: int, label: str) -> str:
    return _require_str(body.get("expected_response"), label=f"{label}[{index}].expected_response")


def _turn_input(raw: object, *, label: str) -> str | dict[str, Any]:
    if isinstance(raw, str):
        return _require_str(raw, label=label)
    body = _object(raw, label=label)
    _reject_unknown(body, _INPUT_KEYS, label=label)
    prompt = _require_str(body.get("prompt"), label=f"{label}.prompt")
    tool = _require_str(body.get("tool"), label=f"{label}.tool")
    args = _object(body.get("args"), label=f"{label}.args")
    if not args:
        raise ValueError(f"{label}.args must be a non-empty object")
    typed_args: dict[str, str] = {}
    for key, value in args.items():
        if not isinstance(value, str) or not value:
            raise ValueError(f"{label}.args.{key} must be a non-empty string")
        typed_args[key] = value
    return {"args": typed_args, "prompt": prompt, "tool": tool}


def _outcomes(raw: object, *, label: str) -> tuple[TurnOutcome, ...]:
    if not isinstance(raw, list) or not raw:
        raise ValueError(f"{label} must be a non-empty list")
    found: list[TurnOutcome] = []
    for index, item in enumerate(raw):
        body = _object(item, label=f"{label}[{index}]")
        _reject_unknown(body, _OUTCOME_KEYS, label=f"{label}[{index}]")
        status = _require_str(body.get("status"), label=f"{label}[{index}].status")
        tool_calls = _str_tuple(body.get("tool_calls"), label=f"{label}[{index}].tool_calls", allow_empty=True)
        replayed = body.get("replayed")
        if not isinstance(replayed, bool):
            raise ValueError(f"{label}[{index}].replayed must be a boolean")
        if "balance" not in body:
            raise ValueError(f"{label}[{index}].balance is required")
        balance = body.get("balance")
        if balance is not None and not isinstance(balance, str):
            raise ValueError(f"{label}[{index}].balance must be a string or null")
        excludes_raw = body.get("result_excludes", [])
        excludes = _str_tuple(excludes_raw, label=f"{label}[{index}].result_excludes", allow_empty=True)
        found.append(
            TurnOutcome(
                status=status,
                tool_calls=tool_calls,
                replayed=replayed,
                balance=balance,
                result_excludes=excludes,
            )
        )
    return tuple(found)


def _str_tuple(raw: object, *, label: str, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{label} must be a list")
    if not raw and not allow_empty:
        raise ValueError(f"{label} must be a non-empty list")
    items: list[str] = []
    for index, item in enumerate(raw):
        items.append(_require_str(item, label=f"{label}[{index}]"))
    return tuple(items)


def _require_str(raw: object, *, label: str) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return raw


def _object(raw: object, *, label: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object")
    typed: dict[str, Any] = {}
    for key, value in raw.items():
        if not isinstance(key, str):
            raise ValueError(f"{label} keys must be strings")
        typed[key] = value
    return typed


def _reject_unknown(body: Mapping[str, Any], allowed: frozenset[str], *, label: str) -> None:
    extra = sorted(set(body) - allowed)
    if extra:
        raise ValueError(f"{label} has unknown keys: {extra}")

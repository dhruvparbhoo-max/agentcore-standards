"""Answer-versus-sources rubric and an offline scorer.

``LexicalGroundednessScorer`` checks claims as substrings of the supplied
sources. It is the runnable stub. ``Builtin.Faithfulness`` is the service
evaluator that asks the same question of spans; the optional Evaluators
adapter can request it, and that call does not replace this rubric.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Protocol, runtime_checkable

from agentcore_eval.datasets import read_json
from agentcore_eval.harness import RuntimeHarness
from agentcore_eval.model import Eval, EvalContext

GROUNDEDNESS_SCHEMA = "agentcore-standards.groundedness.v1"
_ABSTAIN = "i do not have a source"
_EXPECTATIONS = frozenset({"supported", "unsupported", "contradicted", "abstain"})
_TOP_KEYS = frozenset({"schema_version", "rubric", "cases"})
_RUBRIC_KEYS = frozenset({"name", "allow_abstain", "require_citation", "minimum_score"})
_CASE_KEYS = frozenset({"name", "answer", "claims", "sources", "contradictions", "expect"})
_SOURCE_KEYS = frozenset({"source_id", "text"})


class SourceSpan:
    """One source the answer is allowed to rely on."""

    def __init__(self, *, source_id: str, text: str) -> None:
        self.source_id = source_id
        self.text = text


class GroundednessRubric:
    """How an answer is scored against sources."""

    def __init__(self, *, name: str, allow_abstain: bool, require_citation: bool, minimum_score: float) -> None:
        if not 0.0 <= minimum_score <= 1.0:
            raise ValueError("minimum_score must be between 0 and 1")
        self.name = name
        self.allow_abstain = allow_abstain
        self.require_citation = require_citation
        self.minimum_score = minimum_score


class GroundednessCase:
    """One answer, the claims it must support, and the expected label."""

    def __init__(
        self,
        *,
        name: str,
        answer: str,
        claims: tuple[str, ...],
        sources: tuple[SourceSpan, ...],
        contradictions: tuple[str, ...],
        expect: str,
    ) -> None:
        self.name = name
        self.answer = answer
        self.claims = claims
        self.sources = sources
        self.contradictions = contradictions
        self.expect = expect


class GroundednessScore:
    """Result of scoring one answer. ``score`` is 1.0 only when every claim is supported."""

    def __init__(
        self,
        *,
        score: float,
        supported: tuple[str, ...],
        unsupported: tuple[str, ...],
        contradicted: tuple[str, ...],
        abstained: bool,
    ) -> None:
        self.score = score
        self.supported = supported
        self.unsupported = unsupported
        self.contradicted = contradicted
        self.abstained = abstained


class GroundednessPack:
    """Rubric plus the cases that exercise it."""

    def __init__(self, *, rubric: GroundednessRubric, cases: tuple[GroundednessCase, ...]) -> None:
        self.rubric = rubric
        self.cases = cases


@runtime_checkable
class GroundednessScorer(Protocol):
    """Score an answer against sources. Implementations must be deterministic for a fixed case."""

    def score(self, case: GroundednessCase, rubric: GroundednessRubric) -> GroundednessScore:
        """Return the score for ``case`` under ``rubric``."""


class LexicalGroundednessScorer:
    """Substring scorer. A claim is supported when it appears in the answer and in a source."""

    def score(self, case: GroundednessCase, rubric: GroundednessRubric) -> GroundednessScore:
        answer = case.answer.casefold()
        source_text = "\n".join(source.text for source in case.sources).casefold()
        contradicted = tuple(
            phrase
            for phrase in case.contradictions
            if phrase.casefold() in answer and phrase.casefold() not in source_text
        )
        supported: list[str] = []
        unsupported: list[str] = []
        for claim in case.claims:
            folded = claim.casefold()
            if folded in answer and folded in source_text:
                supported.append(claim)
            else:
                unsupported.append(claim)
        if rubric.require_citation and case.sources and not _cites(case):
            unsupported.append("missing citation")
        if contradicted:
            return _score(0.0, supported, unsupported, contradicted, abstained=False)
        if not case.claims and not case.contradictions:
            abstained = rubric.allow_abstain and _ABSTAIN in answer
            return _score(
                1.0 if abstained else 0.0,
                (),
                () if abstained else ("no checkable claim",),
                (),
                abstained=abstained,
            )
        if not case.claims:
            return _score(0.0, (), ("no checkable claim",), (), abstained=False)
        return _score(len(supported) / len(case.claims), supported, unsupported, (), abstained=False)


def load_groundedness_pack(name: str = "groundedness.json") -> GroundednessPack:
    """Load the packaged rubric and cases."""
    return parse_groundedness_pack(read_json(name))


def parse_groundedness_pack(payload: Mapping[str, Any]) -> GroundednessPack:
    """Validate ``payload``. Unknown keys are errors."""
    _reject_unknown(payload, _TOP_KEYS, label="groundedness pack")
    schema_version = _require_str(payload.get("schema_version"), label="schema_version")
    if schema_version != GROUNDEDNESS_SCHEMA:
        raise ValueError(f"schema_version must be {GROUNDEDNESS_SCHEMA}")
    rubric = _rubric(payload.get("rubric"))
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError("cases must be a non-empty list")
    cases: list[GroundednessCase] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_cases):
        case = _case(raw, label=f"cases[{index}]")
        if case.name in seen:
            raise ValueError(f"duplicate groundedness case {case.name}")
        seen.add(case.name)
        cases.append(case)
    return GroundednessPack(rubric=rubric, cases=tuple(cases))


def assert_groundedness(
    score: GroundednessScore,
    *,
    expect: str,
    minimum: float,
) -> None:
    """Raise ``AssertionError`` when ``score`` does not meet ``expect``."""
    if expect not in _EXPECTATIONS:
        raise AssertionError(f"unknown groundedness expectation {expect}")
    if expect == "supported":
        _require(
            score.score >= minimum and not score.unsupported and not score.contradicted and not score.abstained,
            f"expected supported score >= {minimum}, got {score.score} unsupported={score.unsupported!r}",
        )
        return
    if expect == "unsupported":
        _require(bool(score.unsupported) and not score.contradicted, f"expected unsupported, got {score.unsupported!r}")
        return
    if expect == "contradicted":
        _require(bool(score.contradicted) and score.score == 0.0, f"expected contradicted, got {score.contradicted!r}")
        return
    _require(score.abstained and score.score >= minimum, f"expected abstain, score={score.score}")


def groundedness_evals(scorer: GroundednessScorer, pack: GroundednessPack) -> tuple[Eval, ...]:
    """One eval per case."""
    return tuple(_case_eval(scorer, pack.rubric, case) for case in pack.cases)


def _case_eval(scorer: GroundednessScorer, rubric: GroundednessRubric, case: GroundednessCase) -> Eval:
    def setup(harness: RuntimeHarness, ctx: EvalContext) -> None:
        ctx.session = harness.start(actor_id="actor-groundedness", agent_version=ctx.agent_version)

    def act(harness: RuntimeHarness, ctx: EvalContext) -> None:
        del harness, ctx

    def assert_(harness: RuntimeHarness, ctx: EvalContext) -> None:
        del harness, ctx
        assert_groundedness(scorer.score(case, rubric), expect=case.expect, minimum=rubric.minimum_score)

    return Eval(
        name=f"groundedness.{case.name}",
        rubric=f"[{rubric.name}] {case.expect}: score the answer against its sources",
        setup=setup,
        act=act,
        assert_=assert_,
    )


def _cites(case: GroundednessCase) -> bool:
    answer = case.answer.casefold()
    return any(source.source_id.casefold() in answer for source in case.sources)


def _score(
    score: float,
    supported: Sequence[str],
    unsupported: Sequence[str],
    contradicted: Sequence[str],
    *,
    abstained: bool,
) -> GroundednessScore:
    return GroundednessScore(
        score=score,
        supported=tuple(supported),
        unsupported=tuple(unsupported),
        contradicted=tuple(contradicted),
        abstained=abstained,
    )


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _rubric(raw: object) -> GroundednessRubric:
    body = _object(raw, label="rubric")
    _reject_unknown(body, _RUBRIC_KEYS, label="rubric")
    minimum = body.get("minimum_score")
    if isinstance(minimum, bool) or not isinstance(minimum, (int, float)):
        raise ValueError("rubric.minimum_score must be a number")
    allow_abstain = body.get("allow_abstain")
    require_citation = body.get("require_citation")
    if not isinstance(allow_abstain, bool) or not isinstance(require_citation, bool):
        raise ValueError("rubric.allow_abstain and require_citation must be booleans")
    return GroundednessRubric(
        name=_require_str(body.get("name"), label="rubric.name"),
        allow_abstain=allow_abstain,
        require_citation=require_citation,
        minimum_score=float(minimum),
    )


def _case(raw: object, *, label: str) -> GroundednessCase:
    body = _object(raw, label=label)
    _reject_unknown(body, _CASE_KEYS, label=label)
    name = _require_str(body.get("name"), label=f"{label}.name")
    if any(char.isspace() for char in name):
        raise ValueError(f"{label}.name must not contain spaces")
    expect = _require_str(body.get("expect"), label=f"{label}.expect")
    if expect not in _EXPECTATIONS:
        raise ValueError(f"{label}.expect must be one of {sorted(_EXPECTATIONS)}")
    return GroundednessCase(
        name=name,
        answer=_require_str(body.get("answer"), label=f"{label}.answer"),
        claims=_str_tuple(body.get("claims"), label=f"{label}.claims"),
        sources=_sources(body.get("sources"), label=f"{label}.sources"),
        contradictions=_str_tuple(body.get("contradictions"), label=f"{label}.contradictions"),
        expect=expect,
    )


def _sources(raw: object, *, label: str) -> tuple[SourceSpan, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{label} must be a list")
    found: list[SourceSpan] = []
    for index, item in enumerate(raw):
        body = _object(item, label=f"{label}[{index}]")
        _reject_unknown(body, _SOURCE_KEYS, label=f"{label}[{index}]")
        found.append(
            SourceSpan(
                source_id=_require_str(body.get("source_id"), label=f"{label}[{index}].source_id"),
                text=_require_str(body.get("text"), label=f"{label}[{index}].text"),
            )
        )
    return tuple(found)


def _str_tuple(raw: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(raw, list):
        raise ValueError(f"{label} must be a list")
    return tuple(_require_str(item, label=f"{label}[{index}]") for index, item in enumerate(raw))


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

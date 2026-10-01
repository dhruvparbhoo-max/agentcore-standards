"""Guardrail eval fixtures and the assert hook lane D will implement.

``GuardrailCheck`` matches DESIGN §2.4: ``apply_input``, ``apply_output``, and
``allow_memory_write``. ``PatternGuard`` is the offline stand-in so these
fixtures run without Bedrock Guardrails. The real client belongs in
``agentcore-guardrails``, which is still a stub.
"""

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable

from agentcore_eval.datasets import read_json
from agentcore_eval.harness import RuntimeHarness
from agentcore_eval.model import Eval, EvalContext

GUARDRAIL_SCHEMA = "agentcore-standards.guardrail-fixtures.v1"
_INJECTION = "ignore previous instructions"
_PII_MARKER = "BLOCK-PII"
_CHANNELS = frozenset({"input", "output", "memory"})
_FIXTURE_KEYS = frozenset({"name", "channel", "text", "expect_allowed", "event"})
_TOP_KEYS = frozenset({"schema_version", "fixtures"})


class GuardDecision:
    """Allow or block, with a short reason for the evidence note."""

    def __init__(self, *, allowed: bool, reason: str) -> None:
        self.allowed = allowed
        self.reason = reason


@runtime_checkable
class GuardrailCheck(Protocol):
    """Eval view of ``Guard.apply_input`` / ``apply_output`` / ``allow_memory_write``."""

    def apply_input(self, text: str) -> GuardDecision:
        """Decide whether ``text`` may enter the agent."""

    def apply_output(self, text: str) -> GuardDecision:
        """Decide whether ``text`` may leave the agent."""

    def allow_memory_write(self, event: Mapping[str, Any]) -> bool:
        """Return whether ``event`` may be stored. Unguarded text must be rejected."""


class GuardrailFixture:
    """One known allow or block case."""

    def __init__(
        self,
        *,
        name: str,
        channel: str,
        text: str,
        expect_allowed: bool,
        event: Mapping[str, Any] | None,
    ) -> None:
        self.name = name
        self.channel = channel
        self.text = text
        self.expect_allowed = expect_allowed
        self.event = None if event is None else dict(event)


class PatternGuard:
    """Fixture rules used until ``agentcore-guardrails`` exists.

    Input is blocked when it contains ``ignore previous instructions``.
    Output is blocked when it contains the synthetic marker ``BLOCK-PII``.
    A memory write is allowed only when ``event["guarded"] is True``.
    """

    def apply_input(self, text: str) -> GuardDecision:
        if _INJECTION in text.casefold():
            return GuardDecision(allowed=False, reason="prompt injection")
        return GuardDecision(allowed=True, reason="allowed")

    def apply_output(self, text: str) -> GuardDecision:
        if _PII_MARKER in text:
            return GuardDecision(allowed=False, reason="synthetic pii marker")
        return GuardDecision(allowed=True, reason="allowed")

    def allow_memory_write(self, event: Mapping[str, Any]) -> bool:
        return event.get("guarded") is True


def load_guardrail_fixtures(name: str = "guardrails.json") -> tuple[GuardrailFixture, ...]:
    """Load the packaged allow/block fixtures."""
    return parse_guardrail_fixtures(read_json(name))


def parse_guardrail_fixtures(payload: Mapping[str, Any]) -> tuple[GuardrailFixture, ...]:
    """Validate ``payload``. Unknown keys are errors."""
    _reject_unknown(payload, _TOP_KEYS, label="guardrail fixtures")
    schema_version = _require_str(payload.get("schema_version"), label="schema_version")
    if schema_version != GUARDRAIL_SCHEMA:
        raise ValueError(f"schema_version must be {GUARDRAIL_SCHEMA}")
    raw_fixtures = payload.get("fixtures")
    if not isinstance(raw_fixtures, list) or not raw_fixtures:
        raise ValueError("fixtures must be a non-empty list")
    fixtures: list[GuardrailFixture] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_fixtures):
        fixture = _fixture(raw, label=f"fixtures[{index}]")
        if fixture.name in seen:
            raise ValueError(f"duplicate fixture name {fixture.name}")
        seen.add(fixture.name)
        fixtures.append(fixture)
    return tuple(fixtures)


def assert_guardrail(guard: GuardrailCheck, fixture: GuardrailFixture) -> None:
    """Raise ``AssertionError`` when ``guard`` disagrees with ``fixture``."""
    allowed = _allowed(guard, fixture)
    if allowed != fixture.expect_allowed:
        raise AssertionError(f"{fixture.name}: expected allowed={fixture.expect_allowed} but got {allowed}")


def guardrail_evals(guard: GuardrailCheck, fixtures: tuple[GuardrailFixture, ...]) -> tuple[Eval, ...]:
    """One eval per fixture. The harness session exists so the runner can record evidence."""
    return tuple(_fixture_eval(guard, fixture) for fixture in fixtures)


def _fixture_eval(guard: GuardrailCheck, fixture: GuardrailFixture) -> Eval:
    expect = "allow" if fixture.expect_allowed else "block"

    def setup(harness: RuntimeHarness, ctx: EvalContext) -> None:
        ctx.session = harness.start(actor_id="actor-guard", agent_version=ctx.agent_version)

    def act(harness: RuntimeHarness, ctx: EvalContext) -> None:
        del harness, ctx

    def assert_(harness: RuntimeHarness, ctx: EvalContext) -> None:
        del harness, ctx
        assert_guardrail(guard, fixture)

    return Eval(
        name=f"guardrail.{fixture.name}",
        rubric=f"[{fixture.channel}] {expect} for fixture {fixture.name}",
        setup=setup,
        act=act,
        assert_=assert_,
    )


def _allowed(guard: GuardrailCheck, fixture: GuardrailFixture) -> bool:
    if fixture.channel == "input":
        return guard.apply_input(fixture.text).allowed
    if fixture.channel == "output":
        return guard.apply_output(fixture.text).allowed
    if fixture.channel == "memory":
        if fixture.event is None:
            raise AssertionError(f"{fixture.name}: memory fixture is missing event")
        return guard.allow_memory_write(fixture.event)
    raise AssertionError(f"{fixture.name}: unknown channel {fixture.channel}")


def _fixture(raw: object, *, label: str) -> GuardrailFixture:
    body = _object(raw, label=label)
    _reject_unknown(body, _FIXTURE_KEYS, label=label)
    name = _require_str(body.get("name"), label=f"{label}.name")
    if any(char.isspace() for char in name):
        raise ValueError(f"{label}.name must not contain spaces")
    channel = _require_str(body.get("channel"), label=f"{label}.channel")
    if channel not in _CHANNELS:
        raise ValueError(f"{label}.channel must be one of {sorted(_CHANNELS)}")
    text = _require_str(body.get("text"), label=f"{label}.text")
    expect_allowed = body.get("expect_allowed")
    if not isinstance(expect_allowed, bool):
        raise ValueError(f"{label}.expect_allowed must be a boolean")
    event: dict[str, Any] | None = None
    if channel == "memory":
        event = _object(body.get("event"), label=f"{label}.event")
        if "guarded" not in event or not isinstance(event.get("guarded"), bool):
            raise ValueError(f"{label}.event.guarded must be a boolean")
    elif "event" in body:
        raise ValueError(f"{label}: event is only valid for the memory channel")
    return GuardrailFixture(name=name, channel=channel, text=text, expect_allowed=expect_allowed, event=event)


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

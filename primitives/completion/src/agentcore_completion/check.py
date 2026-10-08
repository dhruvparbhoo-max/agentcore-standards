"""A completion check that sees only the claim and the evidence.

There is no callback into the proposer and no shared mutable "done" flag.
The check is deterministic: empty output, open todos, tool errors, a required
tool that never ran, or a missing citation each reject the claim.
"""

from __future__ import annotations


class SamePartyError(Exception):
    """The proposer id and the verifier id are the same party."""


class Claim:
    """What the proposer says is finished."""

    def __init__(self, *, task: str, proposed_result: str, proposer_id: str) -> None:
        self.task = _text(task, "task")
        self.proposed_result = proposed_result if isinstance(proposed_result, str) else ""
        self.proposer_id = _text(proposer_id, "proposer id")


class Evidence:
    """Observations collected outside the proposer."""

    def __init__(
        self,
        *,
        tool_calls: int = 0,
        tool_errors: int = 0,
        unfinished_todos: int = 0,
        required_citations: tuple[str, ...] = (),
        observed_citations: tuple[str, ...] = (),
        requires_tool: bool = False,
    ) -> None:
        self.tool_calls = _count(tool_calls, "tool_calls")
        self.tool_errors = _count(tool_errors, "tool_errors")
        self.unfinished_todos = _count(unfinished_todos, "unfinished_todos")
        self.required_citations = tuple(required_citations)
        self.observed_citations = tuple(observed_citations)
        self.requires_tool = requires_tool


class VerifierVerdict:
    """The verifier's decision. Acceptance is false whenever ``reasons`` is non-empty."""

    def __init__(self, *, accepted: bool, reasons: tuple[str, ...], verifier_id: str) -> None:
        self.accepted = accepted
        self.reasons = reasons
        self.verifier_id = verifier_id


class CompletionVerifier:
    """Reject a claim that the same party both proposed and checked."""

    def __init__(self, *, verifier_id: str) -> None:
        self.verifier_id = _text(verifier_id, "verifier id")

    def check(self, claim: Claim, evidence: Evidence) -> VerifierVerdict:
        """Return a verdict. Same-party wiring raises before any accept."""
        if claim.proposer_id == self.verifier_id:
            raise SamePartyError("proposer must not verify its own completion")
        reasons: list[str] = []
        if not claim.proposed_result.strip():
            reasons.append("empty_result")
        if evidence.unfinished_todos > 0:
            reasons.append("todos_open")
        if evidence.tool_errors > 0:
            reasons.append("tool_errors")
        if evidence.requires_tool and evidence.tool_calls < 1:
            reasons.append("tool_missing")
        missing = [item for item in evidence.required_citations if item not in evidence.observed_citations]
        if missing:
            reasons.append("citations_missing")
        return VerifierVerdict(
            accepted=not reasons,
            reasons=tuple(reasons),
            verifier_id=self.verifier_id,
        )


def _text(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError(f"invalid {label}")
    return value.strip()


def _count(value: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be >= 0")
    return value

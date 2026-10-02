"""The proposer and the verifier are different parties."""

import pytest
from agentcore_completion import Claim, CompletionVerifier, Evidence, SamePartyError


def test_a_different_verifier_accepts_complete_evidence() -> None:
    verdict = CompletionVerifier(verifier_id="verifier-1").check(
        Claim(task="cite the refund rule", proposed_result="Refunds use passage refunds.", proposer_id="proposer-1"),
        Evidence(
            tool_calls=1,
            required_citations=("refunds",),
            observed_citations=("refunds",),
            requires_tool=True,
        ),
    )
    assert verdict.accepted
    assert verdict.verifier_id == "verifier-1"
    assert verdict.reasons == ()


def test_the_proposer_cannot_verify_itself() -> None:
    verifier = CompletionVerifier(verifier_id="same-party")
    with pytest.raises(SamePartyError):
        verifier.check(
            Claim(task="done", proposed_result="done", proposer_id="same-party"),
            Evidence(),
        )


def test_open_todos_errors_and_missing_citations_reject() -> None:
    verdict = CompletionVerifier(verifier_id="verifier-1").check(
        Claim(task="close the ticket", proposed_result="   ", proposer_id="proposer-1"),
        Evidence(
            tool_calls=0,
            tool_errors=1,
            unfinished_todos=2,
            required_citations=("policy",),
            observed_citations=(),
            requires_tool=True,
        ),
    )
    assert verdict.accepted is False
    assert "empty_result" in verdict.reasons
    assert "todos_open" in verdict.reasons
    assert "tool_errors" in verdict.reasons
    assert "tool_missing" in verdict.reasons
    assert "citations_missing" in verdict.reasons

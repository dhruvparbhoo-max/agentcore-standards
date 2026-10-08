"""Decide whether a proposed completion is done. The verifier id must differ from the proposer."""

from agentcore_completion.check import Claim, CompletionVerifier, Evidence, SamePartyError, VerifierVerdict

__all__ = [
    "Claim",
    "CompletionVerifier",
    "Evidence",
    "SamePartyError",
    "VerifierVerdict",
]

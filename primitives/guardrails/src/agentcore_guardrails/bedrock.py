"""Bedrock ApplyGuardrail adapter. Transport failures become a block, not an allow."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from agentcore_guardrails.decision import Blocked, Sanitized
from agentcore_guardrails.guard import GuardrailBackend


class BedrockApplyClient(Protocol):
    """The subset of the Bedrock runtime client this adapter calls."""

    def apply_guardrail(
        self,
        *,
        guardrailIdentifier: str,
        guardrailVersion: str,
        source: str,
        content: list[dict[str, Any]],
    ) -> Mapping[str, Any]:
        """Apply one guardrail. The caller supplies the identifier from the environment."""


class _BedrockBackend:
    def __init__(self, client: BedrockApplyClient, *, guardrail_id: str, version: str) -> None:
        self._client = client
        self._guardrail_id = guardrail_id
        self._version = version

    def apply(self, *, source: str, text: str) -> Sanitized | Blocked:
        try:
            response = self._client.apply_guardrail(
                guardrailIdentifier=self._guardrail_id,
                guardrailVersion=self._version,
                source=source,
                content=[{"text": {"text": text}}],
            )
        except Exception:
            return Blocked("guardrail_unavailable")
        action = response.get("action")
        if action == "NONE":
            return Sanitized(text)
        outputs = response.get("outputs")
        if isinstance(outputs, list):
            for item in outputs:
                if isinstance(item, Mapping):
                    replaced = item.get("text")
                    if isinstance(replaced, str) and replaced.strip():
                        return Sanitized(replaced, ("bedrock",))
        return Blocked("guardrail_intervened")


def bedrock_backend(client: BedrockApplyClient, *, guardrail_id: str, version: str) -> GuardrailBackend:
    """Build a backend that calls ``apply_guardrail``. Identifiers are names the caller already resolved."""
    if not guardrail_id or not version:
        raise ValueError("guardrail id and version are required")
    return _BedrockBackend(client, guardrail_id=guardrail_id, version=version)

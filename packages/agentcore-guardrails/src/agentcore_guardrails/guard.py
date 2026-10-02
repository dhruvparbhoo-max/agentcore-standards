"""Guard facade. A required service that is missing or failing blocks the text."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from agentcore_guardrails.decision import Blocked, Sanitized
from agentcore_guardrails.pin import LOCAL_POLICY_VERSION, GuardrailPin, local_pin
from agentcore_guardrails.policy import screen_text

_MEMORY_ROLES = frozenset({"user", "assistant", "tool"})


class GuardrailBackend(Protocol):
    """One remote check. Implementations must not include the text in errors."""

    def apply(self, *, source: str, text: str) -> Sanitized | Blocked:
        """Return a decision for ``source`` (``INPUT`` or ``OUTPUT``)."""


class Guard:
    """Local policy plus an optional backend.

    ``require_service`` means a missing or failing backend blocks. It does not
    mean the local policy is skipped. Local blocks still win.
    """

    def __init__(
        self,
        pin: GuardrailPin | None = None,
        *,
        backend: GuardrailBackend | None = None,
        require_service: bool = False,
    ) -> None:
        self.pin = local_pin() if pin is None else pin
        self.pin.assert_policy(LOCAL_POLICY_VERSION)
        self._backend = backend
        self._require_service = require_service

    def apply_input(self, text: str) -> Sanitized | Blocked:
        """Screen text before it enters the agent."""
        return self._apply("INPUT", text)

    def apply_output(self, text: str) -> Sanitized | Blocked:
        """Screen text before it is shown to the user."""
        return self._apply("OUTPUT", text)

    def screen_memory_write(self, event: Mapping[str, object]) -> Sanitized | Blocked:
        """Return the text that may be stored, or a block. Raw text is not preserved on a block."""
        role = event.get("role")
        content = event.get("content")
        actor_id = event.get("actor_id")
        namespace = event.get("namespace")
        if not isinstance(role, str) or role not in _MEMORY_ROLES:
            return Blocked("incomplete_event")
        if not isinstance(content, str) or not isinstance(actor_id, str) or not isinstance(namespace, str):
            return Blocked("incomplete_event")
        if not actor_id.strip() or not namespace.strip():
            return Blocked("incomplete_event")
        source = "INPUT" if role == "user" else "OUTPUT"
        return self._apply(source, content)

    def allow_memory_write(self, event: Mapping[str, object]) -> bool:
        """Return whether ``screen_memory_write`` produced storable text."""
        return isinstance(self.screen_memory_write(event), Sanitized)

    def _apply(self, source: str, text: str) -> Sanitized | Blocked:
        local = screen_text(text)
        if isinstance(local, Blocked):
            return local
        if not self._require_service:
            return local
        if self._backend is None:
            return Blocked("guardrail_unconfigured")
        try:
            remote = self._backend.apply(source=source, text=local.text)
        except Exception:
            return Blocked("guardrail_unavailable")
        if isinstance(remote, Blocked):
            return remote
        redactions = tuple(dict.fromkeys((*local.redactions, *remote.redactions)))
        return Sanitized(remote.text, redactions)

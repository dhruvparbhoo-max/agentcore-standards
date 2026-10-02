"""Guardrail id and policy version. The id is a name, not a resource identifier."""

from __future__ import annotations

import re

LOCAL_POLICY_VERSION = "1.0.0"
LOCAL_GUARDRAIL_ID = "local-policy"
LOCAL_GUARDRAIL_VERSION = "1"

_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class PolicyDrift(Exception):
    """The pinned policy version is not the version this process implements."""

    def __init__(self, pinned: str, expected: str) -> None:
        super().__init__("guardrail policy version drifted")
        self.pinned = pinned
        self.expected = expected


class GuardrailPin:
    """The id and versions a deployment is allowed to enforce."""

    def __init__(self, *, guardrail_id: str, version: str, policy_version: str) -> None:
        self.guardrail_id = _token(guardrail_id, "guardrail id")
        self.version = _token(version, "guardrail version")
        self.policy_version = _token(policy_version, "policy version")

    def assert_policy(self, expected: str) -> None:
        """Raise when ``expected`` is not the pinned local policy version."""
        if self.policy_version != expected:
            raise PolicyDrift(self.policy_version, expected)


def local_pin() -> GuardrailPin:
    """Pin for the in-process policy. No service call is implied."""
    return GuardrailPin(
        guardrail_id=LOCAL_GUARDRAIL_ID,
        version=LOCAL_GUARDRAIL_VERSION,
        policy_version=LOCAL_POLICY_VERSION,
    )


def _token(value: str, label: str) -> str:
    if not isinstance(value, str) or _TOKEN.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")
    return value

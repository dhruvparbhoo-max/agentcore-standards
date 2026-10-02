"""Header names documented by AgentCore Runtime.

The custom actor header is the one a runtime allowlist must include. The local
header is what in-process harnesses set. The workload user header is a different
IAM action and is not accepted as the actor.
"""

from __future__ import annotations

from collections.abc import Mapping

CUSTOM_ACTOR_HEADER = "x-amzn-bedrock-agentcore-runtime-custom-actor-id"
LOCAL_ACTOR_HEADER = "x-agentcore-actor-id"
RUNTIME_USER_HEADER = "x-amzn-bedrock-agentcore-runtime-user-id"
RUNTIME_SESSION_HEADER = "x-amzn-bedrock-agentcore-runtime-session-id"

_MAX = 256


class ActorMissing(Exception):
    """No actor header was present. The user-id header does not fill this in."""


class SessionMismatch(Exception):
    """The context session id and the session header disagree."""


def require_actor_id(headers: Mapping[str, str]) -> str:
    """Return the actor id. Custom header wins over the local header."""
    folded = _fold(headers)
    for name in (CUSTOM_ACTOR_HEADER, LOCAL_ACTOR_HEADER):
        value = folded.get(name)
        if value:
            return _field(value, "actor id")
    raise ActorMissing("actor id is required")


def require_session_id(headers: Mapping[str, str], *, context_session_id: str | None = None) -> str:
    """Return one session id. Two different non-empty values are an error."""
    folded = _fold(headers)
    header_value = folded.get(RUNTIME_SESSION_HEADER) or ""
    context_value = context_session_id or ""
    if header_value and context_value and header_value != context_value:
        raise SessionMismatch("session id mismatch")
    chosen = context_value or header_value
    if not chosen:
        raise SessionMismatch("session id is required")
    return _field(chosen, "session id")


def _fold(headers: Mapping[str, str]) -> dict[str, str]:
    folded: dict[str, str] = {}
    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        folded[key.strip().lower()] = value.strip()
    return folded


def _field(value: str, label: str) -> str:
    if not value or len(value) > _MAX or any(ord(char) < 32 for char in value):
        raise ValueError(f"invalid {label}")
    return value

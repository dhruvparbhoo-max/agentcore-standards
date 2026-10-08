"""Read actor and session identifiers from Runtime headers. Missing actor is an error."""

from agentcore_identity.headers import (
    CUSTOM_ACTOR_HEADER,
    LOCAL_ACTOR_HEADER,
    RUNTIME_SESSION_HEADER,
    RUNTIME_USER_HEADER,
    ActorMissing,
    SessionMismatch,
    require_actor_id,
    require_session_id,
)

__all__ = [
    "CUSTOM_ACTOR_HEADER",
    "LOCAL_ACTOR_HEADER",
    "RUNTIME_SESSION_HEADER",
    "RUNTIME_USER_HEADER",
    "ActorMissing",
    "SessionMismatch",
    "require_actor_id",
    "require_session_id",
]

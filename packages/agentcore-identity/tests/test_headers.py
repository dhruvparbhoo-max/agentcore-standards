"""Actor comes from the custom or local header. The workload user header is not the actor."""

import pytest
from agentcore_identity import (
    CUSTOM_ACTOR_HEADER,
    LOCAL_ACTOR_HEADER,
    RUNTIME_SESSION_HEADER,
    RUNTIME_USER_HEADER,
    ActorMissing,
    SessionMismatch,
    require_actor_id,
    require_session_id,
)


def test_custom_actor_header_wins_over_the_local_header() -> None:
    actor = require_actor_id(
        {
            CUSTOM_ACTOR_HEADER: "actor-custom",
            LOCAL_ACTOR_HEADER: "actor-local",
            RUNTIME_USER_HEADER: "user-workload",
        }
    )
    assert actor == "actor-custom"


def test_local_header_is_used_when_the_custom_header_is_absent() -> None:
    assert require_actor_id({LOCAL_ACTOR_HEADER.upper(): "actor-local"}) == "actor-local"


def test_user_header_alone_is_not_an_actor() -> None:
    with pytest.raises(ActorMissing):
        require_actor_id({RUNTIME_USER_HEADER: "user-workload"})


def test_session_header_and_context_must_agree() -> None:
    assert (
        require_session_id(
            {RUNTIME_SESSION_HEADER: "session-1"},
            context_session_id="session-1",
        )
        == "session-1"
    )
    with pytest.raises(SessionMismatch):
        require_session_id({RUNTIME_SESSION_HEADER: "session-1"}, context_session_id="session-2")
    with pytest.raises(SessionMismatch):
        require_session_id({})

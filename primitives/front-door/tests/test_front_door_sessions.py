from __future__ import annotations

import pytest
from agentcore_front_door import SessionBinder, SessionRejected

SECRET = b"s" * 32


def test_empty_request_mints_an_owned_id_of_at_least_33_chars() -> None:
    binder = SessionBinder(SECRET)
    session = binder.resolve("alice", None)
    assert len(session) >= 33
    assert binder.owns("alice", session)
    assert not binder.owns("bob", session)


def test_an_owned_id_round_trips_unchanged() -> None:
    binder = SessionBinder(SECRET)
    session = binder.resolve("alice", "")
    assert binder.resolve("alice", session) == session


def test_another_callers_id_is_refused() -> None:
    binder = SessionBinder(SECRET)
    alices = binder.resolve("alice", None)
    with pytest.raises(SessionRejected, match="another caller"):
        binder.resolve("bob", alices)


def test_a_short_raw_id_is_refused() -> None:
    with pytest.raises(SessionRejected, match="at least 33"):
        SessionBinder(SECRET).resolve("alice", "too-short")


def test_a_short_id_with_the_callers_own_tag_is_still_refused() -> None:
    binder = SessionBinder(SECRET)
    tag = binder.caller_tag("alice")
    with pytest.raises(SessionRejected):
        binder.resolve("alice", f"s-{tag}-x")


def test_a_long_raw_id_is_namespaced_under_the_caller() -> None:
    binder = SessionBinder(SECRET)
    raw = "client-chosen-session-id-0123456789abcdef"
    alice, bob = binder.resolve("alice", raw), binder.resolve("bob", raw)
    assert alice != bob
    assert binder.owns("alice", alice) and binder.owns("bob", bob)
    assert binder.resolve("alice", raw) == alice


def test_bad_characters_are_refused() -> None:
    with pytest.raises(SessionRejected, match="characters"):
        SessionBinder(SECRET).resolve("alice", "x" * 40 + "/../")


def test_channel_ids_are_stable_and_keyed() -> None:
    first = SessionBinder(SECRET).channel_session("chan", "conv")
    assert first == SessionBinder(SECRET).channel_session("chan", "conv")
    assert first != SessionBinder(b"t" * 32).channel_session("chan", "conv")
    assert len(first) >= 33


def test_weak_secret_and_low_minimum_are_rejected() -> None:
    with pytest.raises(ValueError):
        SessionBinder(b"short")
    with pytest.raises(ValueError):
        SessionBinder(SECRET, min_length=16)

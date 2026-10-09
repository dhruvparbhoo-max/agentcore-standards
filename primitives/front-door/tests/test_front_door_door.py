from __future__ import annotations

import json
from typing import Any

import pytest
from agentcore_front_door import (
    ACTOR_HEADER,
    CallRequest,
    CapReached,
    MemoryStore,
    QuotaExceeded,
    Quotas,
    Refused,
    SessionBinder,
    Switch,
    SwitchedOff,
    VerifiedCaller,
)
from agentcore_front_door.door import AuditUnavailable, BadSession, SessionBusy, UnknownAgent
from botocore.exceptions import ClientError
from front_door_fakes import SECRET, FakeRuntime, make_door, policy, settings

ALICE = VerifiedCaller(user_id="alice", kind="user", team="finance", tenant="acme", token="t")
BOB = VerifiedCaller(user_id="bob", kind="user", team="finance")


def _call(door: Any, caller: VerifiedCaller = ALICE, **kwargs: Any) -> Any:
    request = CallRequest(caller=caller, agent=kwargs.pop("agent", "policy-qa"), payload={"prompt": "hi"}, **kwargs)
    return door.call(request)


def test_a_call_invokes_runtime_with_a_bound_session_and_the_actor_header(
    runtime: FakeRuntime, store: MemoryStore
) -> None:
    result = _call(make_door(runtime, store))
    sent = runtime.calls[0]
    assert sent["qualifier"] == "DEV"
    assert sent["runtimeSessionId"] == result.session_id
    assert SessionBinder(SECRET).owns("alice", result.session_id)
    assert sent["_headers"][ACTOR_HEADER] == "alice"
    assert json.loads(sent["payload"]) == {"prompt": "hi"}
    assert result.release_id == "rel-1"


def test_every_call_writes_accepted_completed_and_cost_rows(runtime: FakeRuntime, store: MemoryStore) -> None:
    runtime.reply["usage"] = {"model_calls": 2, "input_tokens": 1000, "output_tokens": 200, "model": "eu.model-a"}
    result = _call(make_door(runtime, store))
    phases = [(row["kind"], row.get("phase")) for row in store.audit]
    assert phases == [("audit", "accepted"), ("audit", "completed"), ("cost", None)]
    completed, cost = store.audit[1], store.audit[2]
    assert completed["user"] == "alice" and completed["agent"] == "policy-qa"
    assert completed["release_id"] == "rel-1" and completed["latency_ms"] >= 0
    assert completed["session"] and completed["session"] != result.session_id
    assert cost["usd"] == pytest.approx((1000 * 3 + 200 * 15) / 1_000_000)
    assert cost["source"] == "reported"
    assert result.cost.usd == cost["usd"]


def test_no_usage_is_recorded_as_unreported(runtime: FakeRuntime, store: MemoryStore) -> None:
    result = _call(make_door(runtime, store))
    assert result.cost.source == "unreported" and result.cost.usd == 0


def test_a_short_session_id_is_refused_and_audited(runtime: FakeRuntime, store: MemoryStore) -> None:
    with pytest.raises(BadSession):
        _call(make_door(runtime, store), session_id="short")
    assert runtime.calls == []
    assert store.audit[-1]["phase"] == "refused" and store.audit[-1]["outcome"] == "bad_session"


def test_someone_elses_session_is_refused(runtime: FakeRuntime, store: MemoryStore) -> None:
    door = make_door(runtime, store)
    alices = _call(door).session_id
    with pytest.raises(BadSession, match="another caller"):
        _call(door, BOB, session_id=alices)


def test_unknown_agent_is_refused(runtime: FakeRuntime, store: MemoryStore) -> None:
    with pytest.raises(UnknownAgent):
        _call(make_door(runtime, store), agent="nope")


def test_a_second_call_in_the_same_session_is_refused_while_the_first_runs(
    runtime: FakeRuntime, store: MemoryStore
) -> None:
    door = make_door(runtime, store)
    session = SessionBinder(SECRET).resolve("alice", None)
    seen: list[str] = []

    def overlap() -> None:
        runtime.during = None
        with pytest.raises(SessionBusy):
            _call(door, session_id=session)
        seen.append("refused")

    runtime.during = overlap
    _call(door, session_id=session)
    assert seen == ["refused"]
    assert store.leases == {}
    _call(door, session_id=session)


def test_quota_refuses_the_call_and_no_session_starts(runtime: FakeRuntime, store: MemoryStore) -> None:
    door = make_door(runtime, store, door_settings=settings(quotas=Quotas(user_daily=2)))
    _call(door)
    _call(door)
    with pytest.raises(QuotaExceeded) as caught:
        _call(door)
    assert caught.value.code == "user_daily"
    assert len(runtime.calls) == 2


def test_per_minute_rate(runtime: FakeRuntime, store: MemoryStore) -> None:
    door = make_door(runtime, store)
    for _ in range(4):
        _call(door)
    with pytest.raises(QuotaExceeded, match="user rate"):
        _call(door)


@pytest.mark.parametrize(
    ("scope", "name", "source"),
    [("agent", "policy-qa", "chat"), ("tool", "search_policies_kb", "chat"), ("source", "chat", "chat")],
)
def test_kill_switch_stops_the_call_before_quota_counts(
    runtime: FakeRuntime, store: MemoryStore, scope: str, name: str, source: str
) -> None:
    store.put_switch(Switch(scope=scope, name=name, enabled=False, reason="incident 7"))
    with pytest.raises(SwitchedOff, match="incident 7"):
        _call(make_door(runtime, store), source=source)
    assert runtime.calls == []
    assert not any(key.startswith("quota#") for key in store.counters)


def test_switch_back_on_lets_calls_through(runtime: FakeRuntime, store: MemoryStore) -> None:
    store.put_switch(Switch(scope="agent", name="policy-qa", enabled=False))
    store.put_switch(Switch(scope="agent", name="policy-qa", enabled=True))
    _call(make_door(runtime, store))


def test_turn_cap_per_session(runtime: FakeRuntime, store: MemoryStore) -> None:
    door = make_door(runtime, store, door_settings=settings(quotas=Quotas(user_per_minute=0)))
    session = _call(door).session_id
    _call(door, session_id=session)
    _call(door, session_id=session)
    with pytest.raises(CapReached) as caught:
        _call(door, session_id=session)
    assert caught.value.code == "session_turns"
    _call(door)


def test_monthly_spend_cap_pauses_the_agent(runtime: FakeRuntime, store: MemoryStore) -> None:
    runtime.reply["usage"] = {"model_calls": 1, "input_tokens": 0, "output_tokens": 1_000_000, "model": "eu.model-a"}
    door = make_door(runtime, store, policies=[policy(monthly_cap_usd=10, max_usd_per_run=20)])
    door.settings = settings(user_monthly_usd=0, team_monthly_usd=0)
    _call(door)
    with pytest.raises(CapReached) as caught:
        _call(door)
    assert caught.value.code == "agent_monthly_spend"


def test_user_monthly_spend_cap(runtime: FakeRuntime, store: MemoryStore) -> None:
    runtime.reply["usage"] = {"model_calls": 1, "input_tokens": 0, "output_tokens": 200_000, "model": "eu.model-a"}
    door = make_door(runtime, store, policies=[policy(max_usd_per_run=20)])
    _call(door)
    with pytest.raises(CapReached, match="user monthly"):
        _call(door)
    _call(door, BOB)


def test_step_and_run_spend_breaches_are_flagged(runtime: FakeRuntime, store: MemoryStore) -> None:
    runtime.reply["usage"] = {"model_calls": 9, "input_tokens": 0, "output_tokens": 100_000, "model": "eu.model-a"}
    result = _call(make_door(runtime, store))
    assert result.breaches == ("steps", "run_spend")
    assert store.audit[1]["breaches"] == ["steps", "run_spend"]


def test_audit_unavailable_means_no_call(runtime: FakeRuntime, store: MemoryStore) -> None:
    store.fail_audit = True
    with pytest.raises(AuditUnavailable):
        _call(make_door(runtime, store))
    assert runtime.calls == []
    assert store.leases == {}


def test_runtime_error_is_a_502_and_still_audited(store: MemoryStore) -> None:
    error = ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow"}}, "InvokeAgentRuntime")
    runtime = FakeRuntime(error=error)
    result = _call(make_door(runtime, store))
    assert result.status_code == 502
    assert store.audit[1]["outcome"] == "ThrottlingException"


def test_user_agents_refuse_a_bare_service_caller(runtime: FakeRuntime, store: MemoryStore) -> None:
    job = VerifiedCaller(user_id="ambient-worker", kind="service", consent_ref="consent#1")
    with pytest.raises(Refused, match="signed-in user"):
        _call(make_door(runtime, store), job, source="job")


def test_service_agents_take_service_callers_and_audit_the_consent(runtime: FakeRuntime, store: MemoryStore) -> None:
    job = VerifiedCaller(user_id="ambient-worker", kind="service", consent_ref="consent#1", on_behalf_of="alice")
    door = make_door(runtime, store, policies=[policy(agent="ambient", acts_as="service", tools=[])])
    _call(door, job, agent="ambient", source="job", job_id="job-1")
    accepted = store.audit[0]
    assert accepted["consent_ref"] == "consent#1" and accepted["on_behalf_of"] == "alice"
    assert accepted["job_id"] == "job-1" and accepted["caller_kind"] == "service"


def test_undeployed_agent_is_refused(runtime: FakeRuntime, store: MemoryStore) -> None:
    with pytest.raises(Refused, match="no runtime"):
        _call(make_door(runtime, store, policies=[policy(runtime_arn="")]))


def test_a_profile_arn_is_priced_as_the_profile_it_copies() -> None:
    from agentcore_front_door.cost import REPORTED, UNPRICED, Usage, price_usage
    from agentcore_front_door.policy import Price

    arn = "arn:" + "aws:bedrock:eu-west-2:111111111111:application-inference-profile/abc"
    usage = Usage(model_calls=1, input_tokens=1_000_000, output_tokens=0, model=arn, reported=True)
    prices = {"eu.model": Price(3.0, 15.0)}
    assert price_usage(usage, prices).source == UNPRICED
    priced = price_usage(usage, prices, aliases={arn: "eu.model"})
    assert (priced.usd, priced.source) == (3.0, REPORTED)

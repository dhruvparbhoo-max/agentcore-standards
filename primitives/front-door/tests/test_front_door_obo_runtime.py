from __future__ import annotations

import io
from typing import Any

import pytest
from agentcore_front_door import (
    OBO_HEADER,
    CallRequest,
    MemoryStore,
    OboExchanger,
    OboFailed,
    RuntimeInvoker,
    VerifiedCaller,
    decode_obo,
)
from agentcore_front_door.runtime import RuntimeFailed
from botocore.exceptions import ClientError
from front_door_fakes import FakeRuntime, make_door, policy

OBO_POLICY = policy(
    workload_name="policy-qa-workload",
    obo=[{"provider": "hr-api", "scopes": ["hr.read"], "audiences": ["hr"]}],
)
ALICE = VerifiedCaller(user_id="alice", kind="user", token="user-jwt")


class Identity:
    def __init__(self, *, token: str | None = "hr-token") -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.token = token

    def get_workload_access_token_for_jwt(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("workload", kwargs))
        return {"workloadAccessToken": "wat"}

    def get_resource_oauth2_token(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("resource", kwargs))
        return {"accessToken": self.token} if self.token else {"authorizationUrl": "https://consent.invalid"}


def test_exchange_makes_the_two_sdk_calls() -> None:
    identity = Identity()
    tokens = OboExchanger(identity).exchange(ALICE, OBO_POLICY)
    assert tokens.tokens == {"hr-api": "hr-token"}
    assert identity.calls[0] == ("workload", {"workloadName": "policy-qa-workload", "userToken": "user-jwt"})
    resource = identity.calls[1][1]
    assert resource["oauth2Flow"] == "ON_BEHALF_OF_TOKEN_EXCHANGE"
    assert resource["workloadIdentityToken"] == "wat"
    assert resource["scopes"] == ["hr.read"] and resource["audiences"] == ["hr"]
    assert "hr-token" not in repr(tokens)


def test_no_obo_targets_means_no_exchange() -> None:
    identity = Identity()
    assert OboExchanger(identity).exchange(ALICE, policy()).tokens == {}
    assert identity.calls == []


def test_consent_url_is_refused() -> None:
    with pytest.raises(OboFailed, match="consent"):
        OboExchanger(Identity(token=None)).exchange(ALICE, OBO_POLICY)


def test_service_caller_cannot_exchange() -> None:
    job = VerifiedCaller(user_id="w", kind="service", consent_ref="c", on_behalf_of="alice")
    with pytest.raises(OboFailed, match="no signed-in user"):
        OboExchanger(Identity()).exchange(job, OBO_POLICY)


def test_door_forwards_tokens_on_the_custom_header_and_audits_only_provider_names(
    runtime: FakeRuntime, store: MemoryStore
) -> None:
    door = make_door(runtime, store, policies=[OBO_POLICY], exchanger=OboExchanger(Identity()))
    door.call(CallRequest(caller=ALICE, agent="policy-qa", payload={"prompt": "hi"}))
    assert decode_obo(runtime.calls[0]["_headers"][OBO_HEADER]) == {"hr-api": "hr-token"}
    assert store.audit[0]["obo_providers"] == ["hr-api"]
    assert "hr-token" not in repr(store.audit)


class Events:
    def __init__(self) -> None:
        self.handlers: dict[str, list[Any]] = {}

    def register_first(self, name: str, handler: Any) -> None:
        self.handlers.setdefault(name, []).insert(0, handler)

    def unregister(self, name: str, handler: Any) -> None:
        self.handlers[name].remove(handler)


class Request:
    def __init__(self) -> None:
        self.headers: dict[str, str] = {}


class SigningClient:
    def __init__(self) -> None:
        self.meta = type("Meta", (), {"events": Events()})()
        self.seen: dict[str, str] = {}

    def invoke_agent_runtime(self, **kwargs: Any) -> dict[str, Any]:
        request = Request()
        for handler in self.meta.events.handlers["before-sign.bedrock-agentcore.InvokeAgentRuntime"]:
            handler(request=request)
        self.seen = request.headers
        return {"statusCode": 200, "contentType": "application/json", "response": io.BytesIO(b'{"ok": true}')}

    def stop_runtime_session(self, **kwargs: Any) -> dict[str, Any]:
        raise ClientError({"Error": {"Code": "ResourceNotFoundException", "Message": "gone"}}, "StopRuntimeSession")


def test_headers_go_on_before_sign_and_are_unregistered() -> None:
    client = SigningClient()
    reply = RuntimeInvoker(client).invoke(
        runtime_arn="rt", qualifier="DEV", session_id="s" * 40, actor_id="alice", payload={}
    )
    assert reply.body == {"ok": True}
    assert client.seen == {"X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id": "alice"}
    assert client.meta.events.handlers["before-sign.bedrock-agentcore.InvokeAgentRuntime"] == []


def test_stop_on_a_stopped_session_is_not_an_error() -> None:
    assert RuntimeInvoker(SigningClient()).stop(runtime_arn="rt", qualifier="DEV", session_id="s" * 40) is False


def test_non_json_reply_is_a_runtime_failure() -> None:
    class Bad(FakeRuntime):
        def invoke_agent_runtime(self, **kwargs: Any) -> dict[str, Any]:
            return {"statusCode": 200, "contentType": "application/json", "response": io.BytesIO(b"nope")}

    with pytest.raises(RuntimeFailed):
        RuntimeInvoker(Bad()).invoke(runtime_arn="rt", qualifier="DEV", session_id="s" * 40, actor_id="a", payload={})

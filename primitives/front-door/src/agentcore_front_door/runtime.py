"""Call AgentCore Runtime for one bound session, and stop a session.

Headers are added on botocore's ``before-sign`` event for ``InvokeAgentRuntime``,
the same way ``agentcore_eval.runtime_client`` does it. Runtime forwards only
``Authorization`` and ``X-Amzn-Bedrock-AgentCore-Runtime-Custom-*`` headers that
the runtime's ``requestHeaderAllowlist`` names, so the actor and the
on-behalf-of tokens ride on custom headers.
"""

from __future__ import annotations

import base64
import json
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from agentcore_front_door.obo import OboTokens

ACTOR_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id"
OBO_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Obo-Tokens"
_INVOKE_EVENT = "before-sign.bedrock-agentcore.InvokeAgentRuntime"
_STOPPED = frozenset({"ResourceNotFoundException", "ResourceNotFound", "NotFoundException"})


class RuntimeClient(Protocol):
    def invoke_agent_runtime(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def stop_runtime_session(self, **kwargs: Any) -> Mapping[str, Any]: ...


class RuntimeFailed(Exception):
    """Runtime returned an error or a body the front door cannot read."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RuntimeReply:
    status_code: int
    body: Mapping[str, Any]


def encode_obo(tokens: OboTokens) -> str:
    raw = json.dumps(tokens.tokens, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_obo(value: str) -> dict[str, str]:
    """What an agent calls on the forwarded header to get its provider tokens back."""
    if not value:
        return {}
    padded = value + "=" * (-len(value) % 4)
    decoded = json.loads(base64.urlsafe_b64decode(padded.encode()))
    if not isinstance(decoded, dict):
        raise ValueError("obo header must carry a JSON object")
    return {str(k): str(v) for k, v in decoded.items()}


class RuntimeInvoker:
    def __init__(self, client: RuntimeClient) -> None:
        self._client = client
        self._lock = threading.Lock()

    def invoke(
        self,
        *,
        runtime_arn: str,
        qualifier: str,
        session_id: str,
        actor_id: str,
        payload: Mapping[str, Any],
        obo: OboTokens | None = None,
    ) -> RuntimeReply:
        headers = {ACTOR_HEADER: actor_id}
        if obo is not None and obo.tokens:
            headers[OBO_HEADER] = encode_obo(obo)
        kwargs: dict[str, Any] = {
            "agentRuntimeArn": runtime_arn,
            "qualifier": qualifier,
            "runtimeSessionId": session_id,
            "payload": json.dumps(dict(payload)).encode("utf-8"),
            "contentType": "application/json",
            "accept": "application/json",
        }
        try:
            response = self._with_headers(kwargs, headers)
        except Exception as exc:
            raise RuntimeFailed(_error_code(exc), f"InvokeAgentRuntime failed: {type(exc).__name__}") from exc
        return RuntimeReply(status_code=int(response.get("statusCode", 200)), body=_decode(response))

    def stop(self, *, runtime_arn: str, qualifier: str, session_id: str) -> bool:
        """``StopRuntimeSession``. False when the session had already stopped."""
        try:
            self._client.stop_runtime_session(
                agentRuntimeArn=runtime_arn, qualifier=qualifier, runtimeSessionId=session_id
            )
        except Exception as exc:
            if _error_code(exc) in _STOPPED:
                return False
            raise
        return True

    def _with_headers(self, kwargs: dict[str, Any], headers: Mapping[str, str]) -> Mapping[str, Any]:
        events = getattr(getattr(self._client, "meta", None), "events", None)
        if events is None:
            return self._client.invoke_agent_runtime(**kwargs, _headers=dict(headers))

        def add_headers(request: Any, **_ignored: Any) -> None:
            for name, value in headers.items():
                request.headers[name] = value

        with self._lock:
            events.register_first(_INVOKE_EVENT, add_headers)
            try:
                return self._client.invoke_agent_runtime(**kwargs)
            finally:
                events.unregister(_INVOKE_EVENT, add_headers)


def _decode(response: Mapping[str, Any]) -> Mapping[str, Any]:
    body = response.get("response")
    if body is None or not hasattr(body, "read"):
        raise RuntimeFailed("no_body", "Runtime response had no readable body")
    raw = body.read()
    if "text/event-stream" in str(response.get("contentType", "")):
        return {"stream": bytes(raw).decode("utf-8")}
    try:
        decoded = json.loads(bytes(raw).decode("utf-8"))
    except ValueError as exc:
        raise RuntimeFailed("bad_body", "Runtime response was not JSON") from exc
    if not isinstance(decoded, Mapping):
        raise RuntimeFailed("bad_body", "Runtime response must be a JSON object")
    return decoded


def _error_code(exc: Exception) -> str:
    return str(getattr(exc, "response", {}).get("Error", {}).get("Code", "")) or type(exc).__name__

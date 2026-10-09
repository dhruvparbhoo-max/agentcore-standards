"""On-behalf-of token exchange for ``identity.acts_as: user``.

Two calls on the ``bedrock-agentcore`` data plane, the same ones the AgentCore
SDK's ``IdentityClient.get_workload_access_token`` and ``get_token`` make
(``bedrock_agentcore/services/identity.py``, Apache-2.0):

1. ``GetWorkloadAccessTokenForJWT(workloadName, userToken)``.
2. ``GetResourceOauth2Token(workloadIdentityToken, resourceCredentialProviderName,
   scopes, oauth2Flow="ON_BEHALF_OF_TOKEN_EXCHANGE", audiences, resources)``.

The result is scoped to that user and that provider. A response that asks for
an interactive consent URL is refused: the front door never waits for a browser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agentcore_front_door.caller import USER, VerifiedCaller
from agentcore_front_door.governance import Refused
from agentcore_front_door.policy import AgentPolicy, OboTarget

OBO_FLOW = "ON_BEHALF_OF_TOKEN_EXCHANGE"


class IdentityClient(Protocol):
    def get_workload_access_token_for_jwt(self, **kwargs: Any) -> dict[str, Any]: ...

    def get_resource_oauth2_token(self, **kwargs: Any) -> dict[str, Any]: ...


class OboFailed(Refused):
    status = 403


@dataclass(frozen=True)
class OboTokens:
    """Provider name to access token. Never logged, never written to the audit row."""

    tokens: dict[str, str] = field(default_factory=dict, repr=False)

    @property
    def providers(self) -> tuple[str, ...]:
        return tuple(sorted(self.tokens))


class OboExchanger:
    def __init__(self, client: IdentityClient) -> None:
        self._client = client

    def exchange(self, caller: VerifiedCaller, policy: AgentPolicy) -> OboTokens:
        if policy.acts_as != USER or not policy.obo:
            return OboTokens()
        if caller.kind != USER or not caller.token:
            raise OboFailed("obo_no_user", "this agent acts as the user, and there is no signed-in user token")
        if not policy.workload_name:
            raise OboFailed("obo_no_workload", "the agent policy names no workload identity")
        try:
            workload = self._client.get_workload_access_token_for_jwt(
                workloadName=policy.workload_name, userToken=caller.token
            )["workloadAccessToken"]
        except Exception as exc:
            raise OboFailed("obo_workload", f"workload token exchange failed: {type(exc).__name__}") from exc
        return OboTokens({target.provider: self._resource_token(str(workload), target) for target in policy.obo})

    def _resource_token(self, workload: str, target: OboTarget) -> str:
        request: dict[str, Any] = {
            "workloadIdentityToken": workload,
            "resourceCredentialProviderName": target.provider,
            "scopes": list(target.scopes),
            "oauth2Flow": OBO_FLOW,
        }
        if target.audiences:
            request["audiences"] = list(target.audiences)
        if target.resources:
            request["resources"] = list(target.resources)
        try:
            response = self._client.get_resource_oauth2_token(**request)
        except Exception as exc:
            raise OboFailed("obo_exchange", f"{target.provider}: token exchange failed: {type(exc).__name__}") from exc
        token = response.get("accessToken")
        if not isinstance(token, str) or not token:
            raise OboFailed("obo_consent", f"{target.provider}: the exchange asked for interactive consent")
        return token

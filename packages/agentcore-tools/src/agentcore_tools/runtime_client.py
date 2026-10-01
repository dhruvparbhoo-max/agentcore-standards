"""Control-plane client for AgentCore Gateway.

``sync`` calls ``create_gateway_target`` for the Lambda target and
``create_policy`` for each Cedar statement. It does not call the MCP data plane.
Identifiers and the Lambda function identifier come from the environment.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from typing import Any, Protocol

from agentcore_tools.errors import GatewayConfigError
from agentcore_tools.gateway import build_lambda_target_request, build_policy_request
from agentcore_tools.naming import require_agent_version, require_cedar_resource, require_resource_id
from agentcore_tools.registry import ToolRegistry

_ENV_NAMES = (
    "AWS_REGION",
    "AGENTCORE_GATEWAY_ID",
    "AGENTCORE_POLICY_ENGINE_ID",
    "AGENTCORE_TOOLS_LAMBDA_ARN",
    "AGENTCORE_GATEWAY_RESOURCE",
)
_LAMBDA_PREFIX = "arn:" + "aws:" + "lambda:"
_CONFLICT_CODES = frozenset({"ConflictException", "Conflict", "ResourceConflictException"})


class GatewayControlPlane(Protocol):
    """Subset of the bedrock-agentcore-control client used to attach tools."""

    def create_gateway_target(
        self,
        *,
        gatewayIdentifier: str,
        name: str,
        targetConfiguration: Mapping[str, Any],
        credentialProviderConfigurations: Sequence[Mapping[str, str]],
    ) -> Mapping[str, Any]:
        """Create one Gateway target."""

    def create_policy(
        self,
        *,
        policyEngineId: str,
        name: str,
        validationMode: str,
        description: str,
        definition: Mapping[str, Any],
        clientToken: str,
    ) -> Mapping[str, Any]:
        """Create one Cedar policy."""


class GatewaySyncResult:
    """Control-plane responses from one sync. Policy responses are empty when nothing is permitted."""

    def __init__(
        self,
        *,
        target_response: Mapping[str, Any],
        policy_responses: tuple[Mapping[str, Any], ...],
    ) -> None:
        self.target_response = dict(target_response)
        self.policy_responses = policy_responses


class AgentCoreGatewayClient:
    """Binds a registry's Lambda target and Cedar statements to a Gateway."""

    def __init__(
        self,
        *,
        region: str,
        gateway_id: str,
        policy_engine_id: str,
        lambda_arn: str,
        gateway_resource: str,
        control: GatewayControlPlane,
    ) -> None:
        if not region or any(ord(char) < 32 for char in region):
            raise GatewayConfigError("AWS_REGION is required")
        self._region = region
        self._gateway_id = require_resource_id(gateway_id)
        self._policy_engine_id = require_resource_id(policy_engine_id)
        self._lambda_arn = _require_lambda_arn(lambda_arn)
        self._gateway_resource = require_cedar_resource(gateway_resource)
        self._control = control

    @classmethod
    def from_env(cls) -> AgentCoreGatewayClient:
        """Build a client from environment variables. Raises when any name is unset."""
        values = {name: os.environ.get(name, "").strip() for name in _ENV_NAMES}
        missing = [name for name, value in values.items() if not value]
        if missing:
            raise GatewayConfigError("missing " + ", ".join(missing))
        import boto3

        control = boto3.client("bedrock-agentcore-control", region_name=values["AWS_REGION"])
        return cls(
            region=values["AWS_REGION"],
            gateway_id=values["AGENTCORE_GATEWAY_ID"],
            policy_engine_id=values["AGENTCORE_POLICY_ENGINE_ID"],
            lambda_arn=values["AGENTCORE_TOOLS_LAMBDA_ARN"],
            gateway_resource=values["AGENTCORE_GATEWAY_RESOURCE"],
            control=control,
        )

    def sync(self, registry: ToolRegistry, *, agent_version: str, target_name: str) -> GatewaySyncResult:
        """Create the Lambda target and the Cedar statements for ``agent_version``.

        An empty allowlist still creates the target and creates no permit.
        Cedar's default is deny. A conflict on create is treated as the resource
        already existing; other control-plane failures raise ``GatewayConfigError``
        without including the request body.
        """
        binding = registry.binding
        if binding is None:
            raise GatewayConfigError("bind_gateway before syncing")
        if binding.gateway_id != self._gateway_id:
            raise GatewayConfigError("registry gateway id does not match the configured gateway")
        version = require_agent_version(agent_version)
        target = binding.target(target_name)
        request = build_lambda_target_request(
            gateway_id=binding.gateway_id,
            target_name=target.name,
            lambda_arn=self._lambda_arn,
            definitions=registry.lambda_definitions(target.name),
        )
        target_response = _call(
            "create_gateway_target",
            lambda: self._control.create_gateway_target(
                gatewayIdentifier=str(request["gatewayIdentifier"]),
                name=str(request["name"]),
                targetConfiguration=_as_mapping(request["targetConfiguration"]),
                credentialProviderConfigurations=_credentials(request["credentialProviderConfigurations"]),
            ),
        )
        actions = {name: target.visible_name(name) for name in target.tool_names}
        statements = binding.policy.cedar_statements(
            agent_version=version,
            gateway_resource=self._gateway_resource,
            actions=actions,
        )
        responses = tuple(self._submit_policy(statement, version) for statement in statements)
        return GatewaySyncResult(target_response=target_response, policy_responses=responses)

    def _submit_policy(self, statement: str, agent_version: str) -> Mapping[str, Any]:
        policy_request = build_policy_request(
            policy_engine_id=self._policy_engine_id,
            statement=statement,
            agent_version=agent_version,
        )
        definition = policy_request["definition"]
        if not isinstance(definition, Mapping):
            raise GatewayConfigError("create_policy failed")
        return _call(
            "create_policy",
            lambda: self._control.create_policy(
                policyEngineId=str(policy_request["policyEngineId"]),
                name=str(policy_request["name"]),
                validationMode=str(policy_request["validationMode"]),
                description=str(policy_request["description"]),
                definition=definition,
                clientToken=str(policy_request["clientToken"]),
            ),
        )


def _require_lambda_arn(value: str) -> str:
    if not value.startswith(_LAMBDA_PREFIX) or len(value) <= len(_LAMBDA_PREFIX) + 8:
        raise GatewayConfigError("AGENTCORE_TOOLS_LAMBDA_ARN is not a Lambda function identifier")
    if any(ord(char) < 32 for char in value):
        raise GatewayConfigError("AGENTCORE_TOOLS_LAMBDA_ARN is not a Lambda function identifier")
    return value


def _call(operation: str, fn: Any) -> Mapping[str, Any]:
    try:
        response = fn()
    except Exception as exc:
        if _is_conflict(exc):
            return {"status": "EXISTS"}
        raise GatewayConfigError(f"{operation} failed") from exc
    if not isinstance(response, Mapping):
        raise GatewayConfigError(f"{operation} returned an unexpected response")
    return response


def _is_conflict(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if not isinstance(response, Mapping):
        return False
    error = response.get("Error")
    if not isinstance(error, Mapping):
        return False
    code = error.get("Code")
    return isinstance(code, str) and code in _CONFLICT_CODES


def _as_mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    raise GatewayConfigError("create_gateway_target failed")


def _credentials(value: object) -> list[dict[str, str]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise GatewayConfigError("create_gateway_target failed")
    credentials: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise GatewayConfigError("create_gateway_target failed")
        converted: dict[str, str] = {}
        for key, entry in item.items():
            if not isinstance(key, str) or not isinstance(entry, str):
                raise GatewayConfigError("create_gateway_target failed")
            converted[key] = entry
        credentials.append(converted)
    return credentials

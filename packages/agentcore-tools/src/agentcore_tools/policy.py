"""Deny-by-default tool policy.

No permit matches means deny. A forbid matches over a permit. That is the same
posture AgentCore Policy uses for Cedar: default deny, and forbid wins.

Cedar statements generated here are the Gateway attachment. They name the
Gateway-visible action ``target___tool``. They do not embed an agent version,
because Cedar actions are gateway tools. The registry still enforces the
per-agent-version allowlist before a call. Sync one policy engine per agent
version so an older permit does not outlive the version that needed it.
"""

import threading
from collections.abc import Mapping
from enum import StrEnum

from agentcore_tools.naming import (
    require_agent_version,
    require_cedar_action,
    require_cedar_resource,
    require_tool_name,
)


class PolicyDecision(StrEnum):
    """Local authorization result for one agent version and tool."""

    ALLOW = "allow"
    DENY = "deny"


class Policy:
    """Allowlist of tools per agent version. The set starts empty."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._permits: dict[str, set[str]] = {}
        self._forbids: dict[str, set[str]] = {}

    def permit(self, agent_version: str, tool_name: str) -> None:
        """Allow ``tool_name`` for ``agent_version``."""
        version = require_agent_version(agent_version)
        tool = require_tool_name(tool_name)
        with self._lock:
            self._permits.setdefault(version, set()).add(tool)

    def forbid(self, agent_version: str, tool_name: str) -> None:
        """Deny ``tool_name`` for ``agent_version`` even if it is also permitted."""
        version = require_agent_version(agent_version)
        tool = require_tool_name(tool_name)
        with self._lock:
            self._forbids.setdefault(version, set()).add(tool)

    def decision(self, agent_version: str, tool_name: str) -> PolicyDecision:
        """Return allow only when a permit matches and no forbid does."""
        version = require_agent_version(agent_version)
        tool = require_tool_name(tool_name)
        with self._lock:
            if tool in self._forbids.get(version, set()):
                return PolicyDecision.DENY
            if tool in self._permits.get(version, set()):
                return PolicyDecision.ALLOW
            return PolicyDecision.DENY

    def cedar_statements(
        self,
        *,
        agent_version: str,
        gateway_resource: str,
        actions: Mapping[str, str],
    ) -> tuple[str, ...]:
        """Cedar permit or forbid statements for the tools in ``actions``.

        Tools with neither a permit nor a forbid produce no statement. Cedar
        then denies them. A tool that is both permitted and forbidden produces
        only a forbid statement.
        """
        version = require_agent_version(agent_version)
        resource = require_cedar_resource(gateway_resource)
        with self._lock:
            forbids = set(self._forbids.get(version, ()))
            permits = set(self._permits.get(version, ()))
        statements: list[str] = []
        for tool_name, action in actions.items():
            visible = require_cedar_action(action)
            if tool_name in forbids:
                statements.append(_statement("forbid", action=visible, gateway_resource=resource))
            elif tool_name in permits:
                statements.append(_statement("permit", action=visible, gateway_resource=resource))
        return tuple(statements)


def _statement(effect: str, *, action: str, gateway_resource: str) -> str:
    return (
        f"{effect}(\n"
        "  principal,\n"
        f'  action == AgentCore::Action::"{action}",\n'
        f'  resource == AgentCore::Gateway::"{gateway_resource}"\n'
        ");"
    )

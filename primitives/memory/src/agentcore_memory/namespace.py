"""Namespace is the agent version plus the environment. It is not shared across those axes."""

from __future__ import annotations

import re

_PART = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class MemoryNamespace:
    """Scope for one agent version in one environment."""

    def __init__(self, *, agent_version: str, environment: str) -> None:
        self.agent_version = _part(agent_version, "agent version")
        self.environment = _part(environment, "environment")

    @property
    def name(self) -> str:
        return f"{self.agent_version}/{self.environment}"


def _part(value: str, label: str) -> str:
    if not isinstance(value, str) or _PART.fullmatch(value) is None:
        raise ValueError(f"invalid {label}")
    return value

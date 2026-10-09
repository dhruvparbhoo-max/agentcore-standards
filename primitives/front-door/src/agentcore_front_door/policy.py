"""What the front door enforces for one agent, and for the whole environment.

``AgentPolicy`` is rendered from ``pattern.yaml`` by ``agentcore-kit front-door-policy``
so this package does not import the agent build stack. ``DoorSettings`` comes
from the ``front_door`` section of ``config/environments/<env>.yaml``. The quota
knobs follow the governance policy in aws-samples/sample-agent-platform-with-agentcore
``backend/app/services/governance_service.py`` (MIT-0), extended to team and agent.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

POLICIES_ENV = "FRONT_DOOR_AGENTS"
POLICIES_FILE_ENV = "FRONT_DOOR_AGENTS_FILE"
SETTINGS_ENV = "FRONT_DOOR_SETTINGS"


class PolicyError(ValueError):
    """A policy or settings document is missing a field."""


@dataclass(frozen=True)
class OboTarget:
    """One credential provider the agent's tools call as the user."""

    provider: str
    scopes: tuple[str, ...] = ()
    audiences: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentPolicy:
    agent: str
    team: str
    acts_as: str
    endpoint: str
    release_id: str
    tools: tuple[str, ...]
    max_turns: int
    max_steps: int
    timeout_s: int
    session_id_min: int
    max_usd_per_run: float
    monthly_cap_usd: float
    on_cap: str = "pause"
    runtime_arn: str = ""
    workload_name: str = ""
    obo: tuple[OboTarget, ...] = ()
    model_aliases: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> AgentPolicy:
        try:
            return cls(
                agent=str(raw["agent"]),
                team=str(raw["team"]),
                acts_as=str(raw["acts_as"]),
                endpoint=str(raw["endpoint"]),
                release_id=str(raw.get("release_id", "")),
                tools=tuple(str(tool) for tool in raw.get("tools", ())),
                max_turns=_positive(raw["max_turns"], "max_turns"),
                max_steps=_positive(raw["max_steps"], "max_steps"),
                timeout_s=_positive(raw["timeout_s"], "timeout_s"),
                session_id_min=max(33, int(raw.get("session_id_min", 33))),
                max_usd_per_run=float(raw["max_usd_per_run"]),
                monthly_cap_usd=float(raw["monthly_cap_usd"]),
                on_cap=str(raw.get("on_cap", "pause")),
                runtime_arn=str(raw.get("runtime_arn", "")),
                workload_name=str(raw.get("workload_name", "")),
                obo=tuple(_obo(item) for item in raw.get("obo", ())),
                model_aliases={str(k): str(v) for k, v in (raw.get("model_aliases") or {}).items()},
            )
        except KeyError as exc:
            raise PolicyError(f"agent policy is missing {exc.args[0]}") from exc

    def as_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "team": self.team,
            "acts_as": self.acts_as,
            "endpoint": self.endpoint,
            "release_id": self.release_id,
            "tools": list(self.tools),
            "max_turns": self.max_turns,
            "max_steps": self.max_steps,
            "timeout_s": self.timeout_s,
            "session_id_min": self.session_id_min,
            "max_usd_per_run": self.max_usd_per_run,
            "monthly_cap_usd": self.monthly_cap_usd,
            "on_cap": self.on_cap,
            "runtime_arn": self.runtime_arn,
            "workload_name": self.workload_name,
            "obo": [
                {
                    "provider": t.provider,
                    "scopes": list(t.scopes),
                    "audiences": list(t.audiences),
                    "resources": list(t.resources),
                }
                for t in self.obo
            ],
            "model_aliases": dict(self.model_aliases),
        }


@dataclass(frozen=True)
class Quotas:
    """Calls per day per user, team, and agent, and calls per minute per user. Zero means no limit."""

    user_daily: int = 200
    team_daily: int = 2000
    agent_daily: int = 5000
    user_per_minute: int = 10


@dataclass(frozen=True)
class Price:
    input_per_million: float
    output_per_million: float


@dataclass(frozen=True)
class DoorSettings:
    quotas: Quotas = field(default_factory=Quotas)
    user_monthly_usd: float = 0.0
    team_monthly_usd: float = 0.0
    lease_grace_s: int = 30
    prices: Mapping[str, Price] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> DoorSettings:
        quotas = raw.get("quotas") or {}
        prices = raw.get("prices") or {}
        return cls(
            quotas=Quotas(
                user_daily=int(quotas.get("user_daily", Quotas.user_daily)),
                team_daily=int(quotas.get("team_daily", Quotas.team_daily)),
                agent_daily=int(quotas.get("agent_daily", Quotas.agent_daily)),
                user_per_minute=int(quotas.get("user_per_minute", Quotas.user_per_minute)),
            ),
            user_monthly_usd=float(raw.get("user_monthly_usd", 0.0)),
            team_monthly_usd=float(raw.get("team_monthly_usd", 0.0)),
            lease_grace_s=int(raw.get("lease_grace_s", 30)),
            prices={
                str(model): Price(float(rate["input_per_million"]), float(rate["output_per_million"]))
                for model, rate in prices.items()
            },
        )


def policies_from_env(env: Mapping[str, str] | None = None) -> dict[str, AgentPolicy]:
    source = os.environ if env is None else env
    path = source.get(POLICIES_FILE_ENV, "")
    text = Path(path).read_text(encoding="utf-8") if path else source.get(POLICIES_ENV, "[]")
    raw = json.loads(text)
    if isinstance(raw, Mapping):
        raw = [raw]
    if not isinstance(raw, list):
        raise PolicyError(f"{POLICIES_ENV} must be a JSON list of agent policies")
    policies = [AgentPolicy.from_mapping(item) for item in raw]
    return {policy.agent: policy for policy in policies}


def settings_from_env(env: Mapping[str, str] | None = None) -> DoorSettings:
    source = os.environ if env is None else env
    raw = json.loads(source.get(SETTINGS_ENV, "{}"))
    if not isinstance(raw, Mapping):
        raise PolicyError(f"{SETTINGS_ENV} must be a JSON object")
    return DoorSettings.from_mapping(raw)


def _obo(raw: Mapping[str, Any]) -> OboTarget:
    return OboTarget(
        provider=str(raw["provider"]),
        scopes=tuple(str(s) for s in raw.get("scopes", ())),
        audiences=tuple(str(s) for s in raw.get("audiences", ())),
        resources=tuple(str(s) for s in raw.get("resources", ())),
    )


def _positive(value: Any, label: str) -> int:
    number = int(value)
    if number < 1:
        raise PolicyError(f"{label} must be >= 1")
    return number

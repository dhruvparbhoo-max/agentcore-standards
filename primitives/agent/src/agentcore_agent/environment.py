"""One config file per environment: ``config/environments/<name>.yaml``.

Secrets are referenced by name, never inline. ``deployment.mode: production``
turns on the production gate in ``agentcore_agent.production``. The shape
follows the enterprise platform sample's ``platform.yaml`` (Apache-2.0); see
docs/attribution/third-party.md.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from agentcore_agent.schema import LOG_RETENTION_DAYS

PLATFORM_CONTROLS = ("front_door", "guardrails_service", "audit_store", "kill_switch", "quotas")

_ENV_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "environment",
        "deployment",
        "region",
        "endpoint",
        "removal",
        "log_retention_days",
        "secrets",
        "controls",
        "observability",
        "network",
    ],
    "properties": {
        "environment": {"type": "string", "pattern": r"^[a-z][a-z0-9]{1,15}$"},
        "deployment": {
            "type": "object",
            "additionalProperties": False,
            "required": ["mode"],
            "properties": {"mode": {"enum": ["development", "production"]}},
        },
        "region": {"type": "string", "pattern": r"^[a-z]{2}(-[a-z]+)+-\d$"},
        "endpoint": {"type": "string", "pattern": r"^[A-Z][A-Z0-9_]{0,47}$", "not": {"const": "DEFAULT"}},
        "removal": {"enum": ["destroy", "retain"]},
        "log_retention_days": {"enum": list(LOG_RETENTION_DAYS)},
        "secrets": {
            "type": "object",
            "additionalProperties": False,
            "required": ["prefix", "rotation_days"],
            "properties": {
                "prefix": {"type": "string", "pattern": r"^[a-z][a-z0-9-]*(/[a-z0-9-]+)*$"},
                "rotation_days": {"type": "integer", "minimum": 1, "maximum": 365},
            },
        },
        "controls": {
            "type": "object",
            "additionalProperties": False,
            "required": list(PLATFORM_CONTROLS),
            "properties": {name: {"type": "boolean"} for name in PLATFORM_CONTROLS},
        },
        "observability": {
            "type": "object",
            "additionalProperties": False,
            "required": ["alarms", "alarm_email"],
            "properties": {"alarms": {"type": "boolean"}, "alarm_email": {"type": "string"}},
        },
        "network": {
            "type": "object",
            "additionalProperties": False,
            "required": ["mode"],
            "properties": {"mode": {"enum": ["PUBLIC", "VPC"]}},
        },
    },
}


class EnvironmentConfigError(ValueError):
    """The environment file is missing or invalid."""


@dataclass(frozen=True)
class EnvironmentConfig:
    raw: Mapping[str, Any]

    @property
    def name(self) -> str:
        return str(self.raw["environment"])

    @property
    def production(self) -> bool:
        return bool(self.raw["deployment"]["mode"] == "production")

    @property
    def region(self) -> str:
        return str(self.raw["region"])

    @property
    def endpoint(self) -> str:
        return str(self.raw["endpoint"])

    @property
    def retain(self) -> bool:
        return bool(self.raw["removal"] == "retain")

    @property
    def log_retention_days(self) -> int:
        return int(self.raw["log_retention_days"])

    @property
    def secrets_prefix(self) -> str:
        return str(self.raw["secrets"]["prefix"])

    @property
    def rotation_days(self) -> int:
        return int(self.raw["secrets"]["rotation_days"])

    @property
    def controls(self) -> Mapping[str, bool]:
        return dict(self.raw["controls"])

    @property
    def alarm_email(self) -> str:
        return str(self.raw["observability"]["alarm_email"])

    @property
    def network_mode(self) -> str:
        return str(self.raw["network"]["mode"])


def environments_dir(repo_root: Path) -> Path:
    return repo_root / "config" / "environments"


def load_environment(name: str, *, repo_root: Path) -> EnvironmentConfig:
    path = environments_dir(repo_root) / f"{name}.yaml"
    if not path.is_file():
        raise EnvironmentConfigError(f"{path} is missing")
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    problems = validate_environment(raw)
    if problems:
        raise EnvironmentConfigError(f"{path}: " + "; ".join(problems))
    if raw["environment"] != name:
        raise EnvironmentConfigError(f"{path}: environment must be {name!r}")
    return EnvironmentConfig(raw=raw)


def validate_environment(raw: Any) -> list[str]:
    if not isinstance(raw, Mapping):
        return ["environment file must be a mapping"]
    validator = Draft202012Validator(_ENV_SCHEMA)
    problems = [
        f"{'.'.join(str(p) for p in error.absolute_path) or '(top level)'}: {error.message}"
        for error in validator.iter_errors(raw)
    ]
    if problems:
        return problems
    if raw["deployment"]["mode"] == "production":
        if raw["removal"] != "retain":
            problems.append("removal: production retains stateful resources")
        if raw["observability"]["alarms"] and "@" not in raw["observability"]["alarm_email"]:
            problems.append("observability.alarm_email: a monitored inbox when alarms are on")
    return problems

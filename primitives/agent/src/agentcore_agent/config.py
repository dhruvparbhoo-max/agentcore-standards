"""Load and validate ``pattern.yaml``.

Every problem in the file is reported at once, so an author fixes the file in
one pass. The rules that compare two fields live here. The field shape lives in
``schema.PATTERN_SCHEMA``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from agentcore_agent.schema import MCP_SESSION_HEADER, PATTERN_SCHEMA, SESSION_HEADER

PATTERN_FILE = "pattern.yaml"
CUSTOM_HEADER_PREFIX = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-"
ACTOR_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id"
CHAT_IDLE_TIMEOUT_S = 300
CHAT_MAX_LIFETIME_S = 1800


class PatternError(ValueError):
    """``pattern.yaml`` is missing a field or breaks a rule. ``problems`` lists all of them."""

    def __init__(self, path: Path, problems: Sequence[str]) -> None:
        self.path = path
        self.problems = tuple(problems)
        super().__init__(f"{path}: " + "; ".join(self.problems))


@dataclass(frozen=True)
class PatternConfig:
    """A validated ``pattern.yaml`` and the folder it came from."""

    root: Path
    raw: Mapping[str, Any]

    @property
    def name(self) -> str:
        return str(self.raw["name"])

    @property
    def framework(self) -> str:
        return str(self.raw["framework"])

    @property
    def endpoint(self) -> str:
        return str(self.raw["endpoint"])

    @property
    def release_id(self) -> str:
        return str(self.raw["release"]["id"])

    @property
    def tools(self) -> tuple[str, ...]:
        return tuple(self.raw["tools"]["from_registry"])

    @property
    def approval_required_for(self) -> frozenset[str]:
        return frozenset(self.raw["approval"]["required_for"])

    @property
    def runtime_name(self) -> str:
        """AgentCore resource name: letters, digits, and underscores only."""
        cleaned = "".join(char if char.isalnum() else "_" for char in self.name).strip("_")
        return cleaned[:1].upper() + cleaned[1:] if cleaned else "Pattern"

    def section(self, name: str) -> Mapping[str, Any]:
        value = self.raw[name]
        if not isinstance(value, Mapping):
            raise KeyError(name)
        return value

    def path(self, relative: str) -> Path:
        """Resolve a path field against the pattern folder."""
        return self.root / relative

    def system_prompt(self) -> str:
        return self.path(self.raw["prompts"]["system"]).read_text(encoding="utf-8")


def load_pattern(location: Path | str) -> PatternConfig:
    """Read ``pattern.yaml`` from a file or a pattern folder and validate it."""
    path = Path(location)
    if path.is_dir():
        path = path / PATTERN_FILE
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PatternError(path, ["pattern.yaml is missing"]) from exc
    except yaml.YAMLError as exc:
        raise PatternError(path, [f"not valid YAML: {exc}"]) from exc
    problems = validate_pattern(raw, folder_name=path.parent.name)
    if problems:
        raise PatternError(path, problems)
    return PatternConfig(root=path.parent.resolve(), raw=raw)


def validate_pattern(raw: Any, *, folder_name: str | None = None) -> list[str]:
    """Return every schema and cross-field problem. Empty means valid."""
    if not isinstance(raw, Mapping):
        return ["pattern.yaml must be a mapping"]
    validator = Draft202012Validator(PATTERN_SCHEMA)
    problems = [_schema_message(error) for error in sorted(validator.iter_errors(raw), key=lambda e: list(e.path))]
    if problems:
        return problems
    return semantic_problems(raw, folder_name=folder_name)


def semantic_problems(raw: Mapping[str, Any], *, folder_name: str | None = None) -> list[str]:
    """Rules that compare fields. Run only on a schema-valid mapping."""
    problems: list[str] = []

    def require(condition: bool, field: str, expectation: str) -> None:
        if not condition:
            problems.append(f"{field}: {expectation}")

    if folder_name is not None:
        require(raw["name"] == folder_name, "name", f"must match the folder name {folder_name!r}")

    lifecycle = raw["lifecycle"]
    require(
        lifecycle["idle_timeout_s"] <= lifecycle["max_lifetime_s"],
        "lifecycle.idle_timeout_s",
        "must be <= lifecycle.max_lifetime_s",
    )
    if raw["trigger"] == "none" and not lifecycle["resumable"]:
        require(
            lifecycle["idle_timeout_s"] == CHAT_IDLE_TIMEOUT_S and lifecycle["max_lifetime_s"] == CHAT_MAX_LIFETIME_S,
            "lifecycle",
            f"chat patterns use idle_timeout_s {CHAT_IDLE_TIMEOUT_S} and max_lifetime_s {CHAT_MAX_LIFETIME_S}",
        )

    approval = raw["approval"]
    require(
        approval["reviewers"] == (2 if raw["risk_tier"] == "high" else 1),
        "approval.reviewers",
        "2 when risk_tier is high, otherwise 1",
    )
    if raw["trigger"] != "none" and approval["required_for"]:
        require(lifecycle["resumable"], "lifecycle.resumable", "true when a background job can wait for approval")

    memory = raw["memory"]
    if memory["write_policy"] == "off":
        require(not memory["enabled"], "memory.write_policy", "off is allowed only when memory.enabled is false")
    if memory["enabled"]:
        require(memory["write_policy"] == "validated", "memory.write_policy", "validated when memory is enabled")

    knowledge = raw["knowledge"]
    if knowledge["enabled"]:
        require(
            knowledge.get("gateway_target") == "knowledge-base",
            "knowledge.gateway_target",
            "knowledge-base when knowledge is enabled",
        )
        require(
            knowledge.get("filter_from") == "verified-login",
            "knowledge.filter_from",
            "verified-login when knowledge is enabled",
        )
        require("groundedness" in raw["eval"], "eval.groundedness", "required for a retrieval pattern")

    model = raw["model"]
    require(
        bool(model["fallback"].strip()) and model["fallback"] != model["primary"],
        "model.fallback",
        "a second profile, different from model.primary",
    )

    data = raw["data"]
    require(
        data["audit_retention_days"] >= data["log_retention_days"],
        "data.audit_retention_days",
        "at least data.log_retention_days",
    )

    context = raw["context"]
    require(
        context["compaction_at"] < context["token_budget"],
        "context.compaction_at",
        "below context.token_budget",
    )

    runtime = raw["runtime"]
    protocol = runtime.get("protocol", "HTTP")
    expected_header = MCP_SESSION_HEADER if protocol == "MCP" else SESSION_HEADER
    require(runtime["session_header"] == expected_header, "runtime.session_header", f"{expected_header} for {protocol}")
    reserved = [header for header in runtime["header_allowlist"] if not _forwardable(header)]
    require(
        not reserved,
        "runtime.header_allowlist",
        f"only Authorization or {CUSTOM_HEADER_PREFIX}* may be forwarded; reserved: {reserved}",
    )
    require(
        ACTOR_HEADER in runtime["header_allowlist"],
        "runtime.header_allowlist",
        f"must include {ACTOR_HEADER} so the agent knows who is calling",
    )

    cost = raw["cost"]
    require(
        cost["max_usd_per_run"] <= cost["monthly_cap_usd"],
        "cost.max_usd_per_run",
        "must be <= cost.monthly_cap_usd",
    )
    return problems


def _forwardable(header: str) -> bool:
    folded = header.lower()
    if folded == "authorization":
        return True
    if folded.startswith(CUSTOM_HEADER_PREFIX.lower()):
        return True
    return not folded.startswith(("x-amz-", "x-amzn-"))


def _schema_message(error: Any) -> str:
    location = ".".join(str(part) for part in error.absolute_path) or "(top level)"
    return f"{location}: {error.message}"

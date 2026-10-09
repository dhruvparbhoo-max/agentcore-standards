"""Generate the AgentCore CLI project files from ``pattern.yaml``.

``agentcore/agentcore.json`` is the CLI's project file (schema
``https://schema.agentcore.aws.dev/v1/agentcore.json``). A harness pattern also
gets ``harness/harness.json`` and ``harness/system-prompt.md``. The committed
files carry no account id, ARN, or image digest. ``render_deploy_project``
adds those from the environment into a throwaway copy at deploy time.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentcore_agent.config import PatternConfig
from agentcore_agent.environment import EnvironmentConfig

SCHEMA_URL = "https://schema.agentcore.aws.dev/v1/agentcore.json"
AGENTCORE_DIR = "agentcore"
HARNESS_DIR = "harness"
REPO_CONTEXT = "../.."
RUNTIME_VERSION = "PYTHON_3_12"
_EMPTY_SECTIONS = (
    "knowledgeBases",
    "credentials",
    "evaluators",
    "onlineEvalConfigs",
    "agentCoreGateways",
    "policyEngines",
    "configBundles",
    "abTests",
    "datasets",
    "capacityProviders",
    "payments",
)


@dataclass(frozen=True)
class GeneratedFile:
    relative: str
    content: str


def project_name(config: PatternConfig) -> str:
    """CLI project name: starts with a letter, letters and digits only, at most 23 characters."""
    words = [part for part in config.name.replace("_", "-").split("-") if part]
    name = "".join(word[:1].upper() + word[1:] for word in words) or "Pattern"
    if config.name.startswith("_"):
        name = "Pattern" + name
    return name[:23]


def pattern_tags(config: PatternConfig, environment: EnvironmentConfig | None = None) -> dict[str, str]:
    tags = {
        "agentcore:created-by": "agentcore-standards",
        "agentcore:project-name": project_name(config),
        "pattern": config.name,
        "owner": str(config.raw["owner"]),
        "team": str(config.section("model")["team_tag"]),
        "alert-route": str(config.raw["alert_route"]),
        "data-classification": str(config.section("data")["classification"]),
    }
    if environment is not None:
        tags["environment"] = environment.name
    return tags


def render_agentcore_json(
    config: PatternConfig,
    *,
    environment: EnvironmentConfig | None = None,
    release_id: str = "",
    endpoint_version: int | None = None,
    build_context: str = REPO_CONTEXT,
    build_args: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """The CLI project file. Arguments other than ``config`` are deploy-time only."""
    document: dict[str, Any] = {
        "$schema": SCHEMA_URL,
        "name": project_name(config),
        "version": 1,
        "managedBy": "CDK",
        "tags": pattern_tags(config, environment),
        "runtimes": [],
        "memories": _memories(config),
        "harnesses": [],
    }
    for section in _EMPTY_SECTIONS:
        document[section] = []
    if config.framework == "harness":
        document["harnesses"].append({"name": config.runtime_name[:40], "path": HARNESS_DIR})
    else:
        document["runtimes"].append(
            _runtime(
                config,
                environment=environment,
                release_id=release_id,
                endpoint_version=endpoint_version,
                build_context=build_context,
                build_args=build_args,
            )
        )
    return document


def render_harness_json(config: PatternConfig, *, gateway_arn: str = "") -> dict[str, Any]:
    """Managed-loop spec. The gateway tool is added only when a deploy supplies its ARN."""
    lifecycle = config.section("lifecycle")
    tools: list[dict[str, Any]] = []
    if gateway_arn:
        tools.append(
            {
                "type": "agentcore_gateway",
                "name": "gateway",
                "config": {"agentCoreGateway": {"gatewayArn": gateway_arn, "outboundAuth": {"awsIam": {}}}},
            }
        )
    spec: dict[str, Any] = {
        "name": config.runtime_name[:40],
        "model": {"provider": "bedrock", "modelId": str(config.section("model")["primary"])},
        "tools": tools,
        "skills": [],
        "memory": {"mode": "managed"} if config.section("memory")["enabled"] else {"mode": "disabled"},
        "maxIterations": int(lifecycle["max_steps"]),
        "timeoutSeconds": int(lifecycle["timeout_s"]),
        "lifecycleConfig": _lifecycle(config),
        "truncation": {"strategy": "sliding_window"},
    }
    if config.tools:
        spec["allowedTools"] = list(config.tools)
    return spec


def generated_files(config: PatternConfig) -> list[GeneratedFile]:
    """Every file ``generate`` writes into the pattern folder, with committed (deploy-free) content."""
    files = [
        GeneratedFile(f"{AGENTCORE_DIR}/agentcore.json", _dump(render_agentcore_json(config))),
        GeneratedFile(f"{AGENTCORE_DIR}/aws-targets.json", "[]\n"),
    ]
    if config.framework == "harness":
        files.append(GeneratedFile(f"{HARNESS_DIR}/harness.json", _dump(render_harness_json(config))))
        files.append(GeneratedFile(f"{HARNESS_DIR}/system-prompt.md", config.system_prompt()))
    return files


def write_generated(config: PatternConfig) -> list[Path]:
    written: list[Path] = []
    for item in generated_files(config):
        target = config.root / item.relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.content, encoding="utf-8")
        written.append(target)
    return written


def stale_generated(config: PatternConfig) -> list[str]:
    """Generated files that are missing or differ from ``pattern.yaml``. Empty means current."""
    stale: list[str] = []
    for item in generated_files(config):
        target = config.root / item.relative
        if not target.is_file() or target.read_text(encoding="utf-8") != item.content:
            stale.append(item.relative)
    return stale


def render_deploy_project(
    config: PatternConfig,
    *,
    environment: EnvironmentConfig,
    destination: Path,
    repo_root: Path,
    account: str,
    release_id: str,
    endpoint_version: int | None = None,
    build_args: Mapping[str, str] | None = None,
    gateway_arn: str = "",
) -> Path:
    """Write the deploy copy: ``agentcore.json`` with the release and ``aws-targets.json`` with the account.

    ``destination`` is outside git (``build/deploy/<pattern>``). The CLI scaffolds
    its CDK folder there with ``agentcore create --no-agent`` before this runs.
    """
    if not (account.isdigit() and len(account) == 12):
        raise ValueError("account must be a 12-digit AWS account id from the environment")
    agentcore_dir = destination / AGENTCORE_DIR
    agentcore_dir.mkdir(parents=True, exist_ok=True)
    document = render_agentcore_json(
        config,
        environment=environment,
        release_id=release_id,
        endpoint_version=endpoint_version,
        build_context=str(repo_root.resolve()),
        build_args=build_args,
    )
    if config.framework == "harness":
        harness_dir = destination / HARNESS_DIR
        harness_dir.mkdir(parents=True, exist_ok=True)
        (harness_dir / "harness.json").write_text(
            _dump(render_harness_json(config, gateway_arn=gateway_arn)), encoding="utf-8"
        )
        (harness_dir / "system-prompt.md").write_text(config.system_prompt(), encoding="utf-8")
    else:
        document["runtimes"][0]["codeLocation"] = str((config.root / "agent").resolve()) + "/"
    (agentcore_dir / "agentcore.json").write_text(_dump(document), encoding="utf-8")
    targets = [
        {
            "name": environment.name,
            "description": f"{config.name} {environment.name}",
            "account": account,
            "region": environment.region,
        }
    ]
    (agentcore_dir / "aws-targets.json").write_text(_dump(targets), encoding="utf-8")
    return agentcore_dir / "agentcore.json"


def _runtime(
    config: PatternConfig,
    *,
    environment: EnvironmentConfig | None,
    release_id: str,
    endpoint_version: int | None,
    build_context: str,
    build_args: Mapping[str, str] | None,
) -> dict[str, Any]:
    runtime_cfg = config.section("runtime")
    model = config.section("model")
    env_vars = {
        "AGENTCORE_PATTERN": config.name,
        "AGENTCORE_ENVIRONMENT": environment.name if environment else "local",
        "AGENTCORE_RELEASE_ID": release_id,
        "AGENTCORE_ENDPOINT": environment.endpoint if environment else config.endpoint,
        "BEDROCK_MODEL_ID": str(model["primary"]),
        "BEDROCK_FALLBACK_MODEL_ID": str(model["fallback"]),
    }
    runtime: dict[str, Any] = {
        "name": config.runtime_name[:48],
        "description": f"{config.name} pattern ({config.framework})",
        "build": "Container",
        "entrypoint": "main.py",
        "codeLocation": "agent/",
        "dockerfile": f"patterns/{config.name}/agent/Dockerfile",
        "buildContextPath": build_context,
        "runtimeVersion": RUNTIME_VERSION,
        "protocol": runtime_cfg.get("protocol", "HTTP"),
        "networkMode": environment.network_mode if environment else "PUBLIC",
        "requestHeaderAllowlist": list(runtime_cfg["header_allowlist"]),
        "lifecycleConfiguration": _lifecycle(config),
        "instrumentation": {"enableOtel": True},
        "envVars": [{"name": key, "value": value} for key, value in env_vars.items()],
        "tags": pattern_tags(config, environment),
    }
    if build_args:
        runtime["customDockerBuildArgs"] = dict(build_args)
    if endpoint_version is not None:
        endpoint = environment.endpoint if environment else config.endpoint
        runtime["endpoints"] = {endpoint: {"version": endpoint_version}}
    return runtime


def _lifecycle(config: PatternConfig) -> dict[str, int]:
    lifecycle = config.section("lifecycle")
    return {
        "idleRuntimeSessionTimeout": int(lifecycle["idle_timeout_s"]),
        "maxLifetime": int(lifecycle["max_lifetime_s"]),
    }


def _memories(config: PatternConfig) -> list[dict[str, Any]]:
    memory = config.section("memory")
    if not memory["enabled"]:
        return []
    return [
        {
            "name": f"{config.runtime_name[:40]}Memory",
            "eventExpiryDuration": 30,
            "strategies": [{"type": "SEMANTIC", "namespaceTemplates": ["/actors/{actorId}/facts"]}],
        }
    ]


def _dump(document: Any) -> str:
    return json.dumps(document, indent=2, sort_keys=False) + "\n"

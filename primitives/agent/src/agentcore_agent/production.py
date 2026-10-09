"""Production mode: a deploy to a production environment refuses to start without every required control.

The list is docs/design/library.md "Checks", production mode. The gate shape
follows the enterprise platform sample's production preset, which refuses to
synth when a required control is off (Apache-2.0; docs/attribution/third-party.md).
Platform controls (front door, guardrail service, audit store, kill switch,
quotas) are switched on in ``config/environments/<env>.yaml`` once they exist.
"""

from __future__ import annotations

from pathlib import Path

from agentcore_agent.checks import approval_problems, cedar_problems, eval_problems, tracing_problems
from agentcore_agent.config import ACTOR_HEADER, PatternConfig
from agentcore_agent.environment import PLATFORM_CONTROLS, EnvironmentConfig

MAX_PRODUCTION_ROTATION_DAYS = 90


def production_problems(config: PatternConfig, environment: EnvironmentConfig, *, repo_root: Path) -> list[str]:
    """Empty means the deploy may continue. A development environment always passes."""
    if not environment.production:
        return []
    problems: list[str] = []

    def require(condition: bool, field: str, expectation: str) -> None:
        if not condition:
            problems.append(f"{field}: {expectation}")

    for control in PLATFORM_CONTROLS:
        require(environment.controls.get(control, False), f"controls.{control}", "must be on in production")
    require(config.raw["deployment"] == "docker", "deployment", "docker")
    require(config.raw["identity"]["acts_as"] in {"user", "service"}, "identity.acts_as", "set")
    allowlist = config.section("runtime")["header_allowlist"]
    require(ACTOR_HEADER in allowlist, "runtime.header_allowlist", f"must forward {ACTOR_HEADER}")
    require(environment.rotation_days <= MAX_PRODUCTION_ROTATION_DAYS, "secrets.rotation_days", "90 or fewer")
    require(environment.retain, "removal", "retain")
    require(environment.endpoint != "DEV", "endpoint", "a production endpoint, not DEV")
    require(
        int(config.section("data")["log_retention_days"]) >= environment.log_retention_days,
        "data.log_retention_days",
        f"at least the environment's {environment.log_retention_days}",
    )
    problems.extend(f"cedar: {message}" for message in cedar_problems(config))
    problems.extend(f"tracing: {message}" for message in tracing_problems(config))
    problems.extend(f"eval: {message}" for message in eval_problems(config))
    problems.extend(f"approval: {message}" for message in approval_problems(config, repo_root=repo_root))
    return problems

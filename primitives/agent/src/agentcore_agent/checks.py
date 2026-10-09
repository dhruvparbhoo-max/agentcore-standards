"""The kit check: a pattern folder has the twelve items, or CI fails.

docs/design/library.md "The twelve-item kit" lists the items. A missing item is
a problem with the item number, so the author knows which line of the list to
read. The check is offline: it reads files and never calls AWS.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

from agentcore_agent.agentcore_json import render_agentcore_json, stale_generated
from agentcore_agent.config import PatternConfig, PatternError, load_pattern
from agentcore_agent.golden import golden_problems, load_golden
from agentcore_agent.schema import ACTION_CLASSES

RETRIEVAL_TAGS = ("source-backed", "goal-success")
TOOL_FILE = "tool.yaml"
_PERMIT = re.compile(r"\bpermit\s*\((?P<body>.*?)\)\s*(?:when\s*\{.*?\}\s*)?;", re.DOTALL)
_ACTION_NAME = re.compile(r'AgentCore::Action::"(?P<target>[^"]*?)___(?P<tool>[^"]+)"')
_BARE_ACTION = re.compile(r"^\s*action\s*,", re.MULTILINE)


@dataclass(frozen=True)
class KitProblem:
    item: int
    message: str

    def __str__(self) -> str:
        return f"item {self.item}: {self.message}"


def check_kit(folder: Path, *, repo_root: Path) -> list[KitProblem]:
    """Every missing kit item for the pattern in ``folder``. Empty means the kit is complete."""
    problems: list[KitProblem] = []

    def need(condition: bool, item: int, message: str) -> None:
        if not condition:
            problems.append(KitProblem(item, message))

    readme = folder / "README.md"
    need(readme.is_file(), 1, "README.md is missing")
    if readme.is_file():
        need("docker ps" in readme.read_text(encoding="utf-8"), 1, "README.md must give the `docker ps` prerequisite")

    try:
        config = load_pattern(folder)
    except PatternError as exc:
        problems.extend(KitProblem(2, problem) for problem in exc.problems)
        return problems
    need(not config.release_id, 2, "release.id stays blank in git; the deploy stamps it")
    for stale in stale_generated(config):
        problems.append(KitProblem(2, f"{stale} is stale; run `agentcore-kit generate {folder}`"))

    prompt = config.path(config.raw["prompts"]["system"])
    need(prompt.is_file() and bool(prompt.read_text(encoding="utf-8").strip()), 3, f"{prompt.name} is missing or empty")

    problems.extend(KitProblem(4, message) for message in cedar_problems(config))
    problems.extend(KitProblem(5, message) for message in approval_problems(config, repo_root=repo_root))
    problems.extend(KitProblem(6, message) for message in tracing_problems(config))

    tests = folder / "tests"
    need(any(tests.glob("test_*.py")), 7, "tests/ needs unit or contract tests (test_*.py)")
    need(_has_runtime_marker(tests / "e2e"), 7, "tests/e2e needs a test marked @pytest.mark.runtime")

    problems.extend(KitProblem(8, message) for message in eval_problems(config))

    events = folder / "events"
    has_events = any(events.glob("*.json"))
    if config.raw["trigger"] == "none":
        explained = readme.is_file() and "## Events" in readme.read_text(encoding="utf-8")
        need(has_events or explained, 9, "events/ needs a sample, or README.md an `## Events` section saying why not")
    else:
        need(has_events, 9, "events/ needs at least one sample event for `make local`")

    problems.extend(KitProblem(10, message) for message in _uses_build_agent(config))
    problems.extend(KitProblem(12, message) for message in deploy_problems(config))
    need((folder / "docs" / "design.md").is_file(), 12, "docs/design.md is missing")
    return problems


def cedar_problems(config: PatternConfig) -> list[str]:
    """Each listed tool has its own permit; nothing else is permitted; no permit covers every action."""
    path = config.path(config.raw["tools"]["cedar"])
    if not path.is_file():
        return [f"{path.name} is missing"]
    text = _strip_comments(path.read_text(encoding="utf-8"))
    permitted: set[str] = set()
    problems: list[str] = []
    for match in _PERMIT.finditer(text):
        body = match.group("body")
        if _BARE_ACTION.search(body):
            problems.append("a permit covers every action; name each tool")
        permitted.update(found.group("tool") for found in _ACTION_NAME.finditer(body))
    listed = set(config.tools)
    for tool in sorted(listed - permitted):
        problems.append(f"tool {tool} is listed but has no Cedar permit")
    for tool in sorted(permitted - listed):
        problems.append(f"Cedar permits {tool}, which tools.from_registry does not list")
    return problems


def approval_problems(config: PatternConfig, *, repo_root: Path) -> list[str]:
    """A tool whose registry entry sends, spends, deletes, or changes needs approval for that action."""
    problems: list[str] = []
    required = config.approval_required_for
    for tool in config.tools:
        listing = tool_listing(tool, repo_root=repo_root)
        if listing is None:
            problems.append(f"tool {tool} has no primitives/gateway-tools/{tool}/{TOOL_FILE}")
            continue
        action = str(listing.get("action", "read"))
        if action in ACTION_CLASSES and action not in required:
            problems.append(f"tool {tool} does {action}; approval.required_for must list {action}")
    return problems


def tracing_problems(config: PatternConfig) -> list[str]:
    document = render_agentcore_json(config)
    problems: list[str] = []
    for runtime in document["runtimes"]:
        if not runtime.get("instrumentation", {}).get("enableOtel"):
            problems.append(f"runtime {runtime['name']} must enable OpenTelemetry")
    if config.framework != "harness" and not _agent_sources(config):
        problems.append("agent/ has no Python sources")
    return problems


def eval_problems(config: PatternConfig) -> list[str]:
    path = config.path(config.raw["eval"]["golden_set"])
    if not path.is_file():
        return [f"{path.name} is missing"]
    try:
        raw = load_golden(path)
    except ValueError as exc:
        return [str(exc)]
    problems = golden_problems(raw, pattern=config.name)
    if problems or not config.section("knowledge")["enabled"]:
        return problems
    tags = {tag for scenario in raw["scenarios"] for tag in scenario["metadata"]["tags"]}
    for tag in RETRIEVAL_TAGS:
        if tag not in tags:
            problems.append(f"a retrieval pattern needs scenarios tagged {tag}")
    return problems


def deploy_problems(config: PatternConfig) -> list[str]:
    problems: list[str] = []
    if not (config.root / "infra" / "app.py").is_file():
        problems.append("infra/app.py (the CDK deploy) is missing")
    if config.framework == "harness":
        return problems
    dockerfile = config.root / "agent" / "Dockerfile"
    if not dockerfile.is_file():
        return [*problems, "agent/Dockerfile is missing"]
    text = dockerfile.read_text(encoding="utf-8")
    if "BASE_AGENT_IMAGE" not in text:
        problems.append("agent/Dockerfile must build FROM the shared base-agent image")
    if "uv sync --frozen" not in text:
        problems.append("agent/Dockerfile must install with `uv sync --frozen`")
    if "HEALTHCHECK" not in text:
        problems.append("agent/Dockerfile needs a HEALTHCHECK on /ping")
    users = re.findall(r"^USER\s+(\S+)", text.split("FROM")[-1], flags=re.MULTILINE)
    if users and users[-1] in {"root", "0"}:
        problems.append("agent/Dockerfile final stage must not run as root")
    return problems


def tool_listing(tool: str, *, repo_root: Path) -> dict[str, object] | None:
    path = repo_root / "primitives" / "gateway-tools" / tool / TOOL_FILE
    if not path.is_file():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None


def pattern_folders(repo_root: Path) -> list[Path]:
    root = repo_root / "patterns"
    return sorted(path.parent for path in root.glob("*/pattern.yaml"))


def _uses_build_agent(config: PatternConfig) -> list[str]:
    """``build_agent`` applies the guard and the untrusted tags; an agent that skips it skips both."""
    if config.framework == "harness":
        return []
    for source in _agent_sources(config):
        if "build_agent" in source.read_text(encoding="utf-8"):
            return []
    return ["agent code must build its loop with agentcore_agent.build_agent (guard, untrusted tags, tracing)"]


def _agent_sources(config: PatternConfig) -> list[Path]:
    return sorted((config.root / "agent").rglob("*.py"))


def _has_runtime_marker(folder: Path) -> bool:
    return any("pytest.mark.runtime" in path.read_text(encoding="utf-8") for path in folder.glob("test_*.py"))


def _strip_comments(text: str) -> str:
    return "\n".join(line.split("//", 1)[0] for line in text.splitlines())


def format_problems(problems: Iterable[KitProblem]) -> str:
    return "\n".join(f"  - {problem}" for problem in problems)

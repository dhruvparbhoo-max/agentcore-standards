"""``agentcore-kit``: the commands a pattern needs from scaffold to deploy.

Every command except ``doctor`` (AWS part), ``verify``, ``post-events`` (a local
container), and ``publish-tool`` is offline. Exit status is 0 on success and 1 on any problem.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from agentcore_agent.agentcore_json import render_deploy_project, stale_generated, write_generated
from agentcore_agent.checks import check_kit, format_problems, pattern_folders
from agentcore_agent.config import PatternError, load_pattern
from agentcore_agent.environment import EnvironmentConfigError, load_environment
from agentcore_agent.production import production_problems
from agentcore_agent.registry import load_tool, publish, tool_problems
from agentcore_agent.release import release_id, release_inputs

Echo = Callable[[str], None]


def main(argv: Sequence[str] | None = None, *, echo: Echo = print) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        code: int = args.run(args, echo)
    except (PatternError, EnvironmentConfigError, ValueError) as exc:
        echo(f"error: {exc}")
        return 1
    return code


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agentcore-kit", description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd(), help="repository root (default: cwd)")
    commands = parser.add_subparsers(dest="command", required=True)

    generate = commands.add_parser("generate", help="write agentcore/agentcore.json from pattern.yaml")
    generate.add_argument("patterns", nargs="*", type=Path)
    generate.add_argument("--check", action="store_true", help="fail if a generated file is stale; write nothing")
    generate.set_defaults(run=_generate)

    kit = commands.add_parser("check-kit", help="fail when a pattern is missing a kit item")
    kit.add_argument("patterns", nargs="*", type=Path)
    kit.set_defaults(run=_check_kit)

    tools = commands.add_parser("tool-check", help="validate primitives/gateway-tools/*/tool.yaml")
    tools.add_argument("tools", nargs="*", type=Path)
    tools.set_defaults(run=_tool_check)

    doctor = commands.add_parser("doctor", help="read-only checks before a run or a deploy")
    doctor.add_argument("pattern", nargs="?", type=Path)
    doctor.add_argument("--env", default="dev")
    doctor.add_argument("--local", action="store_true", help="only local tools (Python, uv, Docker)")
    doctor.add_argument("--secret", action="append", default=[], help="secret name under the environment prefix")
    doctor.set_defaults(run=_doctor)

    prod = commands.add_parser("production-check", help="refuse a production deploy missing a control")
    prod.add_argument("pattern", type=Path)
    prod.add_argument("--env", required=True)
    prod.set_defaults(run=_production)

    rel = commands.add_parser("release-id", help="print the release id for an image digest")
    rel.add_argument("pattern", type=Path)
    rel.add_argument("--image-digest", required=True)
    rel.add_argument("--inputs", action="store_true", help="also print the inputs the id covers")
    rel.set_defaults(run=_release)

    deploy = commands.add_parser("render-deploy", help="write the deploy copy of agentcore.json outside git")
    deploy.add_argument("pattern", type=Path)
    deploy.add_argument("--env", required=True)
    deploy.add_argument("--destination", type=Path, required=True)
    deploy.add_argument("--account", required=True)
    deploy.add_argument("--release-id", required=True)
    deploy.add_argument("--endpoint-version", type=int)
    deploy.add_argument("--build-arg", action="append", default=[], help="NAME=VALUE for the image build")
    deploy.add_argument("--gateway-arn", default="")
    deploy.set_defaults(run=_render_deploy)

    verify = commands.add_parser("verify", help="compare the deployed runtime with pattern.yaml (needs AWS)")
    verify.add_argument("pattern", type=Path)
    verify.add_argument("--runtime-id", required=True)
    verify.add_argument("--release-id", required=True)
    verify.add_argument("--endpoint", required=True)
    verify.add_argument("--region", required=True)
    verify.set_defaults(run=_verify)

    events = commands.add_parser("post-events", help="post a pattern's events/*.json to a running agent")
    events.add_argument("pattern", type=Path)
    events.add_argument("--url", default="http://localhost:8080")
    events.set_defaults(run=_post_events)

    pub = commands.add_parser("publish-tool", help="create the Agent Registry record for a tool (needs AWS)")
    pub.add_argument("tool", type=Path)
    pub.add_argument("--registry-id", required=True)
    pub.add_argument("--gateway-url", required=True)
    pub.add_argument("--region", required=True)
    pub.set_defaults(run=_publish)
    return parser


def _patterns(args: argparse.Namespace) -> list[Path]:
    chosen: list[Path] = list(args.patterns)
    return chosen or pattern_folders(args.repo_root)


def _generate(args: argparse.Namespace, echo: Echo) -> int:
    failed = 0
    for folder in _patterns(args):
        config = load_pattern(folder)
        if args.check:
            stale = stale_generated(config)
            for name in stale:
                echo(f"{folder}: {name} is stale; run `agentcore-kit generate {folder}`")
            failed += bool(stale)
        else:
            for path in write_generated(config):
                echo(f"wrote {path}")
    return 1 if failed else 0


def _check_kit(args: argparse.Namespace, echo: Echo) -> int:
    failed = 0
    for folder in _patterns(args):
        problems = check_kit(folder, repo_root=args.repo_root)
        if problems:
            failed += 1
            echo(f"FAIL {folder}\n{format_problems(problems)}")
        else:
            echo(f"PASS {folder}")
    return 1 if failed else 0


def _tool_check(args: argparse.Namespace, echo: Echo) -> int:
    import yaml

    folders: list[Path] = list(args.tools) or sorted(
        path.parent for path in (args.repo_root / "primitives" / "gateway-tools").glob("*/tool.yaml")
    )
    failed = 0
    for folder in folders:
        problems = tool_problems(
            yaml.safe_load((folder / "tool.yaml").read_text(encoding="utf-8")), folder_name=folder.name
        )
        if not list((folder / "tests").glob("test_*.py")):
            problems.append("tests/ needs a double-invoke test")
        if not (folder / "Dockerfile").is_file():
            problems.append("Dockerfile is missing")
        failed += bool(problems)
        echo(f"{'FAIL' if problems else 'PASS'} {folder}" + "".join(f"\n  - {p}" for p in problems))
    return 1 if failed else 0


def _doctor(args: argparse.Namespace, echo: Echo) -> int:
    from agentcore_agent.doctor import Doctor, Reporter

    config = load_pattern(args.pattern) if args.pattern else None
    environment = None if args.local else load_environment(args.env, repo_root=args.repo_root)
    return Doctor(
        config=config,
        environment=environment,
        secrets=args.secret,
        reporter=Reporter(echo),
        local_only=args.local,
    ).run()


def _production(args: argparse.Namespace, echo: Echo) -> int:
    config = load_pattern(args.pattern)
    environment = load_environment(args.env, repo_root=args.repo_root)
    problems = production_problems(config, environment, repo_root=args.repo_root)
    kit = check_kit(args.pattern, repo_root=args.repo_root) if environment.production else []
    for problem in [*problems, *(str(p) for p in kit)]:
        echo(f"REFUSE {problem}")
    if problems or kit:
        echo(f"production deploy of {config.name} to {environment.name} refused")
        return 1
    echo(f"production gate passed for {config.name} on {environment.name}")
    return 0


def _release(args: argparse.Namespace, echo: Echo) -> int:
    config = load_pattern(args.pattern)
    echo(release_id(config, image_digest=args.image_digest))
    if args.inputs:
        for key, value in release_inputs(config, image_digest=args.image_digest).items():
            echo(f"  {key}={value}")
    return 0


def _render_deploy(args: argparse.Namespace, echo: Echo) -> int:
    config = load_pattern(args.pattern)
    environment = load_environment(args.env, repo_root=args.repo_root)
    build_args = dict(item.split("=", 1) for item in args.build_arg)
    path = render_deploy_project(
        config,
        environment=environment,
        destination=args.destination,
        repo_root=args.repo_root,
        account=args.account,
        release_id=args.release_id,
        endpoint_version=args.endpoint_version,
        build_args=build_args,
        gateway_arn=args.gateway_arn,
    )
    echo(f"wrote {path}")
    return 0


def _verify(args: argparse.Namespace, echo: Echo) -> int:
    import boto3

    from agentcore_agent.verify import verify_runtime

    config = load_pattern(args.pattern)
    client = boto3.client("bedrock-agentcore-control", region_name=args.region)
    problems = verify_runtime(
        config, client, runtime_id=args.runtime_id, release_id=args.release_id, endpoint=args.endpoint
    )
    for problem in problems:
        echo(f"MISS {problem}")
    echo("verify failed" if problems else f"verified {config.name} release {args.release_id}")
    return 1 if problems else 0


def _post_events(args: argparse.Namespace, echo: Echo) -> int:
    from agentcore_agent.events import post_event, turn_events

    paths = turn_events(args.pattern)
    if not paths:
        echo(f"{args.pattern}: no events with a payload under events/")
        return 1
    failed = 0
    for path in paths:
        outcome = post_event(path, args.url)
        failed += not outcome.passed
        echo(f"{'PASS' if outcome.passed else 'FAIL'} {outcome.name}: {outcome.body.get('status')}")
        for problem in outcome.problems:
            echo(f"  - {problem}")
    return 1 if failed else 0


def _publish(args: argparse.Namespace, echo: Echo) -> int:
    import boto3

    listing = load_tool(args.tool)
    client = boto3.client("bedrock-agentcore-control", region_name=args.region)
    publish(listing, client, registry_id=args.registry_id, gateway_url=args.gateway_url)
    echo(f"listed {listing.name} in registry {args.registry_id}; approve it in the registry before use")
    return 0


if __name__ == "__main__":
    sys.exit(main())

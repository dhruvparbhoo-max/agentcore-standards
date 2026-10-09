"""List and build every container image in the repo.

One image per deployable unit (docs/design/library.md, Deployment):

- ``patterns/<name>/agent/Dockerfile``          -> ``<name>-agent``   on ``base-agent``
- ``primitives/gateway-tools/<name>/Dockerfile`` -> ``tool-<name>``    on ``base-lambda``
- ``primitives/<name>/Dockerfile``               -> ``lambda-<name>``  on ``base-lambda``
  (the front door, approvals, and triggers groups; one handler per Lambda)

The base images build first so each unit's ``FROM ${BASE_*_IMAGE}`` resolves to
the same digest-pinned parents. Build context is always the repo root.

    python scripts/images.py list
    python scripts/images.py build --platform linux/arm64 --tag arm64
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "agentcore-standards"
BASES = {"BASE_AGENT_IMAGE": "base-agent", "BASE_LAMBDA_IMAGE": "base-lambda"}


@dataclass(frozen=True)
class Image:
    name: str
    dockerfile: Path
    base_arg: str | None

    def ref(self, tag: str) -> str:
        return f"{PREFIX}/{self.name}:{tag}"


def bases(root: Path = ROOT) -> list[Image]:
    return [Image(name, root / "docker" / name / "Dockerfile", None) for name in BASES.values()]


def units(root: Path = ROOT) -> list[Image]:
    found: list[Image] = []
    for path in sorted(root.glob("patterns/*/agent/Dockerfile")):
        found.append(_unit(f"{_slug(path.parents[1].name)}-agent", path))
    for path in sorted(root.glob("primitives/gateway-tools/*/Dockerfile")):
        found.append(_unit(f"tool-{_slug(path.parent.name)}", path))
    for path in sorted(root.glob("primitives/*/Dockerfile")):
        found.append(_unit(f"lambda-{_slug(path.parent.name)}", path))
    return found


def build_commands(
    images: Sequence[Image], *, platform: str, tag: str, root: Path = ROOT, load: bool = True
) -> list[list[str]]:
    commands: list[list[str]] = []
    for image in images:
        command = ["docker", "buildx", "build", "--platform", platform, "-t", image.ref(tag)]
        if image.base_arg is None:
            command += ["-f", str(image.dockerfile), str(image.dockerfile.parent)]
        else:
            base = f"{PREFIX}/{BASES[image.base_arg]}:{tag}"
            command += ["--build-arg", f"{image.base_arg}={base}", "-f", str(image.dockerfile), str(root)]
        if load:
            command.insert(3, "--load")
        commands.append(command)
    return commands


def main(argv: Sequence[str] | None = None, run: Callable[[list[str]], int] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="print name, Dockerfile, and base for each unit")
    build = commands.add_parser("build", help="build the base images, then every unit")
    build.add_argument("--platform", default="linux/arm64")
    build.add_argument("--tag", default="arm64")
    build.add_argument("--only", action="append", default=[], help="unit name; repeat for more")
    args = parser.parse_args(argv)

    if args.command == "list":
        for image in units():
            print(f"{image.name}\t{image.dockerfile.relative_to(ROOT)}\t{BASES.get(image.base_arg or '', '-')}")
        return 0

    chosen = [image for image in units() if not args.only or image.name in args.only]
    unknown = set(args.only) - {image.name for image in chosen}
    if unknown:
        print(f"unknown image: {', '.join(sorted(unknown))}", file=sys.stderr)
        return 1
    runner = run or _run
    for command in build_commands([*bases(), *chosen], platform=args.platform, tag=args.tag):
        print("+ " + " ".join(command), flush=True)
        if runner(command) != 0:
            return 1
    return 0


def _unit(name: str, dockerfile: Path) -> Image:
    text = dockerfile.read_text(encoding="utf-8")
    declared = [arg for arg in BASES if f"ARG {arg}" in text]
    if len(declared) != 1:
        raise SystemExit(f"{dockerfile}: declare exactly one of {', '.join(BASES)}")
    return Image(name, dockerfile, declared[0])


def _slug(folder: str) -> str:
    return folder.lstrip("_").replace("_", "-")


def _run(command: list[str]) -> int:
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    sys.exit(main())

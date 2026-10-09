"""Release id: one hash over the bundle that changes behaviour.

The bundle is the prompt files, the model ids, the tool names, the Cedar file,
and the container image digest. A change to any of them is a new release.

The AgentCore CLI builds the runtime image in CodeBuild, so its registry digest
exists only after ``agentcore deploy``. Before deploy, ``build_digest`` stands in
for it: a hash over every tracked file the image build copies plus the digest of
the base image it starts from. ``agentcore-kit verify`` then checks that the
runtime runs a digest-pinned image.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable, Sequence
from pathlib import Path

from agentcore_agent.config import PatternConfig

RELEASE_PREFIX = "rel-"
BUILD_INPUTS = ("pyproject.toml", "uv.lock", "primitives", "docker/base-agent")

ListFiles = Callable[[Path, Sequence[str]], list[str]]


def release_inputs(config: PatternConfig, *, image_digest: str) -> dict[str, str]:
    """The exact inputs the release id covers. Logged next to the id at deploy time."""
    if not image_digest.startswith("sha256:"):
        raise ValueError("image_digest must be a sha256 digest, not a tag")
    model = config.section("model")
    return {
        "cedar": _sha(config.path(config.raw["tools"]["cedar"]).read_bytes()),
        "image": image_digest,
        "model.fallback": str(model["fallback"]),
        "model.primary": str(model["primary"]),
        "prompt.system": _sha(config.path(config.raw["prompts"]["system"]).read_bytes()),
        "tools": ",".join(sorted(config.tools)),
    }


def release_id(config: PatternConfig, *, image_digest: str) -> str:
    canonical = json.dumps(release_inputs(config, image_digest=image_digest), sort_keys=True)
    return RELEASE_PREFIX + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_digest(
    config: PatternConfig, *, repo_root: Path, base_digest: str, list_files: ListFiles | None = None
) -> str:
    """``sha256:`` over the base image digest and each tracked build input, path and content."""
    if not base_digest.startswith("sha256:"):
        raise ValueError("base_digest must be a sha256 digest, not a tag")
    lister = list_files or _git_ls_files
    digest = hashlib.sha256(base_digest.encode("utf-8"))
    for name in sorted(lister(repo_root, [f"patterns/{config.name}", *BUILD_INPUTS])):
        path = repo_root / name
        if not path.is_file():
            continue
        digest.update(f"\0{name}\0{_sha(path.read_bytes())}".encode())
    return "sha256:" + digest.hexdigest()


def _git_ls_files(repo_root: Path, paths: Sequence[str]) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z", "--", *paths], cwd=repo_root, capture_output=True, check=True
    ).stdout.decode("utf-8")
    return [name for name in out.split("\0") if name]

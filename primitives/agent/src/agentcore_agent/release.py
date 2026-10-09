"""Release id: one hash over the bundle that changes behaviour.

The bundle is the prompt files, the model ids, the tool names, the Cedar file,
and the container image digest. A change to any of them is a new release.
"""

from __future__ import annotations

import hashlib
import json

from agentcore_agent.config import PatternConfig

RELEASE_PREFIX = "rel-"


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

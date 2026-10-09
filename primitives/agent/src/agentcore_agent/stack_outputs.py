"""Read the CDK outputs file the foundation and edge stacks write (``cdk deploy --outputs-file``).

The names are the ``CfnOutput`` ids in ``patterns/<name>/infra/app.py``. Values
are resource ids from the account; they live under ``build/deploy/`` and never in git.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

MODEL_PROFILE = "ModelProfileArn"
FALLBACK_PROFILE = "FallbackProfileArn"
NETWORK_SUBNETS = "NetworkSubnets"
NETWORK_SECURITY_GROUPS = "NetworkSecurityGroups"
NETWORK_VPC = "NetworkVpcId"
FRONT_DOOR_ROLE = "FrontDoorRoleArn"
FRONT_DOOR_URL = "FrontDoorUrl"


def load_outputs(*paths: Path) -> dict[str, str]:
    """Every stack's outputs merged into one mapping. A missing file contributes nothing."""
    merged: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError(f"{path}: expected the CDK outputs object")
        for stack in raw.values():
            if isinstance(stack, Mapping):
                merged.update({str(k): str(v) for k, v in stack.items()})
    return merged


def network_config(outputs: Mapping[str, str]) -> dict[str, object] | None:
    """The runtime's ``networkConfig`` for VPC mode, or None when the stack made no network."""
    subnets = _split(outputs.get(NETWORK_SUBNETS, ""))
    groups = _split(outputs.get(NETWORK_SECURITY_GROUPS, ""))
    if not subnets or not groups:
        return None
    config: dict[str, object] = {"subnets": subnets, "securityGroups": groups}
    if outputs.get(NETWORK_VPC):
        config["vpcId"] = outputs[NETWORK_VPC]
    return config


def model_aliases(outputs: Mapping[str, str], *, primary: str, fallback: str) -> dict[str, str]:
    """Profile ARN to the geographic id it copies, so the front door can price the call."""
    aliases: dict[str, str] = {}
    if outputs.get(MODEL_PROFILE):
        aliases[outputs[MODEL_PROFILE]] = primary
    if outputs.get(FALLBACK_PROFILE) and fallback:
        aliases[outputs[FALLBACK_PROFILE]] = fallback
    return aliases


def _split(text: str) -> list[str]:
    return [part for part in (piece.strip() for piece in text.split(",")) if part]

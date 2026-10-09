"""Secrets Manager rotation for tokens the platform issues itself (webhook signing keys, service tokens).

The four steps (createSecret, setSecret, testSecret, finishSecret) and the
AWSPENDING / AWSCURRENT staging follow the AWS Secrets Manager rotation
function template in the user guide ("Lambda rotation functions"). A third-party
API key cannot be minted here; its pattern supplies its own setSecret that calls
the provider, or rotates it by hand inside ``rotation_days``.
"""

from __future__ import annotations

import secrets
from typing import Any

import boto3

PENDING = "AWSPENDING"
CURRENT = "AWSCURRENT"
TOKEN_BYTES = 32


def handler(event: dict[str, Any], context: Any, *, client: Any = None) -> None:
    del context
    client = client or boto3.client("secretsmanager")
    arn = event["SecretId"]
    token = event["ClientRequestToken"]
    step = event["Step"]
    metadata = client.describe_secret(SecretId=arn)
    if not metadata.get("RotationEnabled"):
        raise ValueError("rotation is not enabled for this secret")
    stages = metadata.get("VersionIdsToStages", {})
    if token not in stages:
        raise ValueError("no secret version for this rotation token")
    if CURRENT in stages[token]:
        return
    if PENDING not in stages[token]:
        raise ValueError("this version is not pending rotation")
    if step == "createSecret":
        _create(client, arn, token)
    elif step in {"setSecret", "testSecret"}:
        return
    elif step == "finishSecret":
        _finish(client, arn, token, stages)
    else:
        raise ValueError(f"unknown rotation step {step}")


def _create(client: Any, arn: str, token: str) -> None:
    client.get_secret_value(SecretId=arn, VersionStage=CURRENT)
    try:
        client.get_secret_value(SecretId=arn, VersionId=token, VersionStage=PENDING)
    except client.exceptions.ResourceNotFoundException:
        client.put_secret_value(
            SecretId=arn,
            ClientRequestToken=token,
            SecretString=secrets.token_urlsafe(TOKEN_BYTES),
            VersionStages=[PENDING],
        )


def _finish(client: Any, arn: str, token: str, stages: dict[str, list[str]]) -> None:
    current = next((version for version, labels in stages.items() if CURRENT in labels), None)
    if current == token:
        return
    client.update_secret_version_stage(
        SecretId=arn,
        VersionStage=CURRENT,
        MoveToVersionId=token,
        RemoveFromVersionId=current,
    )

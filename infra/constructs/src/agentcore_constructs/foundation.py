"""Per-pattern foundation: KMS, secrets with rotation, ECR, and a masked log group.

Sources (docs/attribution/third-party.md):

- KMS key with rotation, one secret per name under a prefix, ``grant_read`` to
  one consumer, and DESTROY only in dev: aws-samples/sample-social-intelligence-agents
  ``infra/stacks/social_intelligence_stack.py`` (MIT-0).
- ECR with ``image_scan_on_push`` and a keep-10 lifecycle rule:
  aws-samples/sample-agentcore-enterprise-platform ``stacks/runtime_stack.py`` (Apache-2.0).
- Log retention limited to 30, 90, 180, or 365 days: the same sample's
  ``stacks/observability_stack.py``.
- ``DataProtectionPolicy`` with managed and custom identifiers and allow/deny
  ``logs:Unmask`` policies: aws-samples/cloudwatch-logs-data-protection-policies-with-cdk
  ``stacks/cloudwatch_policies.py`` (MIT-0). Scoped here to this log group, not every log group.
- ``add_rotation_schedule`` with a custom rotation Lambda: the AWS CDK
  ``aws_secretsmanager`` documentation; HostedRotation covers only databases.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

LOG_RETENTION: Mapping[int, logs.RetentionDays] = {
    30: logs.RetentionDays.ONE_MONTH,
    90: logs.RetentionDays.THREE_MONTHS,
    180: logs.RetentionDays.SIX_MONTHS,
    365: logs.RetentionDays.ONE_YEAR,
}
ROTATION_DIR = Path(__file__).resolve().parents[3] / "rotation"


def removal_for(environment: str) -> cdk.RemovalPolicy:
    """DESTROY in dev only. Every other environment keeps its data."""
    return cdk.RemovalPolicy.DESTROY if environment == "dev" else cdk.RemovalPolicy.RETAIN


class RotationFunction(Construct):
    """Container-image rotation Lambda for secrets the platform can reissue itself."""

    def __init__(self, scope: Construct, construct_id: str, *, key: kms.IKey, base_image: str = "") -> None:
        super().__init__(scope, construct_id)
        build_args = {"BASE_LAMBDA_IMAGE": base_image} if base_image else None
        self.function = lambda_.DockerImageFunction(
            self,
            "Function",
            code=lambda_.DockerImageCode.from_image_asset(
                str(ROTATION_DIR),
                platform=cdk.aws_ecr_assets.Platform.LINUX_ARM64,
                build_args=build_args,
            ),
            architecture=lambda_.Architecture.ARM_64,
            timeout=cdk.Duration.seconds(30),
            description="Secrets Manager rotation for platform-issued tokens",
        )
        key.grant_encrypt_decrypt(self.function)


class PatternFoundation(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        pattern: str,
        environment: str,
        log_retention_days: int,
        secrets_prefix: str,
        secret_names: Sequence[str] = (),
        rotation_days: int = 90,
        rotation_function: lambda_.IFunction | None = None,
        custom_identifiers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(scope, construct_id)
        if log_retention_days not in LOG_RETENTION:
            raise ValueError(f"log_retention_days must be one of {sorted(LOG_RETENTION)}")
        removal = removal_for(environment)
        retain = removal == cdk.RemovalPolicy.RETAIN
        cdk.Tags.of(self).add("pattern", pattern)
        cdk.Tags.of(self).add("environment", environment)

        self.key = kms.Key(
            self,
            "Key",
            description=f"CMK for {pattern} {environment} secrets and logs",
            enable_key_rotation=True,
            removal_policy=removal,
        )
        self.key.grant_encrypt_decrypt(iam.ServicePrincipal(f"logs.{cdk.Stack.of(self).region}.amazonaws.com"))

        self.repository = ecr.Repository(
            self,
            "Repository",
            repository_name=f"agentcore-{pattern.strip('_')}-{environment}",
            image_scan_on_push=True,
            image_tag_mutability=ecr.TagMutability.IMMUTABLE,
            removal_policy=removal,
            empty_on_delete=not retain,
            lifecycle_rules=[ecr.LifecycleRule(max_image_count=10, description="Keep last 10 images")],
        )

        identifiers: list[logs.DataIdentifier] = [logs.DataIdentifier.EMAILADDRESS, logs.DataIdentifier.IPADDRESS]
        identifiers.extend(
            logs.CustomDataIdentifier(name, pattern_text) for name, pattern_text in (custom_identifiers or {}).items()
        )
        self.log_group = logs.LogGroup(
            self,
            "Logs",
            log_group_name=f"/agentcore/{pattern.strip('_')}/{environment}",
            retention=LOG_RETENTION[log_retention_days],
            encryption_key=self.key,
            data_protection_policy=logs.DataProtectionPolicy(
                name=f"{pattern.strip('_')}-{environment}-pii",
                description="Mask personal data in agent logs",
                identifiers=identifiers,
            ),
            removal_policy=removal,
        )

        self.secrets: dict[str, secretsmanager.Secret] = {}
        for name in secret_names:
            secret = secretsmanager.Secret(
                self,
                f"Secret{_logical(name)}",
                secret_name=f"{secrets_prefix}/{name}",
                description=f"{pattern} {environment}: {name}",
                encryption_key=self.key,
                removal_policy=removal,
            )
            if rotation_function is not None:
                secret.add_rotation_schedule(
                    "Rotation",
                    rotation_lambda=rotation_function,
                    automatically_after=cdk.Duration.days(rotation_days),
                )
            self.secrets[name] = secret

    def grant_secret_read(self, name: str, grantee: iam.IGrantable) -> None:
        """Read access to one secret, plus decrypt on its key, for one consumer."""
        self.secrets[name].grant_read(grantee)

    def unmask_policies(self) -> tuple[iam.ManagedPolicy, iam.ManagedPolicy]:
        """(allow, deny) ``logs:Unmask`` on this log group. Attach allow to the few who may see raw values."""
        resource = [self.log_group.log_group_arn]
        allow = iam.ManagedPolicy(
            self,
            "UnmaskAllow",
            statements=[iam.PolicyStatement(effect=iam.Effect.ALLOW, actions=["logs:Unmask"], resources=resource)],
        )
        deny = iam.ManagedPolicy(
            self,
            "UnmaskDeny",
            statements=[iam.PolicyStatement(effect=iam.Effect.DENY, actions=["logs:Unmask"], resources=resource)],
        )
        return allow, deny


def _logical(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in name.replace("_", "-").split("-") if part)

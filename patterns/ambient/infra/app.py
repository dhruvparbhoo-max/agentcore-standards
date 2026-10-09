"""CDK app for the template's supporting resources. The AgentCore CLI deploys the runtime itself.

Two stacks, deployed either side of ``agentcore deploy`` by ``scripts/deploy.sh``:

1. ``<Project>-<env>`` (before the runtime): the KMS key, the ECR repository,
   the masked log group, the pattern's secrets, the per-agent model profiles,
   the alarm topic and, in a VPC environment, the network with its endpoints,
   DNS Firewall and (when asked) a Code Interpreter in VPC mode. Its outputs
   feed ``agentcore-kit render-deploy --outputs``.
2. ``<Project>-<env>-edge`` (after the runtime, so its ARN is known): the front
   door and the runtime alarms. It is only synthesised when ``-c runtime_arn=...``
   and ``-c front_door_policy=<file>`` are given. The issuer and audience of the
   sign-in tokens come from ``FRONT_DOOR_ISSUER`` and ``FRONT_DOOR_AUDIENCE``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import aws_cdk as cdk
from agentcore_agent import load_pattern
from agentcore_agent.agentcore_json import pattern_tags, project_name
from agentcore_agent.config import PatternConfig
from agentcore_agent.environment import EnvironmentConfig, load_environment
from agentcore_agent.stack_outputs import (
    FALLBACK_PROFILE,
    FRONT_DOOR_ROLE,
    FRONT_DOOR_URL,
    MODEL_PROFILE,
    NETWORK_SECURITY_GROUPS,
    NETWORK_SUBNETS,
    NETWORK_VPC,
)
from agentcore_constructs import (
    AgentModelProfile,
    FrontDoor,
    NetworkFoundation,
    PatternFoundation,
    RuntimeAlarms,
    image_asset,
)
from aws_cdk import aws_kms as kms
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions

PATTERN = Path(__file__).resolve().parents[1]
REPO = PATTERN.parents[1]
SECRETS: tuple[str, ...] = ()


def build(app: cdk.App, env_name: str, *, runtime_arn: str = "", front_door_policy: str = "") -> cdk.Stack:
    """Returns the foundation stack. The edge stack is added to ``app`` when the runtime ARN is given."""
    config = load_pattern(PATTERN)
    environment = load_environment(env_name, repo_root=REPO)
    prefix = f"{project_name(config)}-{environment.name}"
    location = cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=environment.region)
    tags = pattern_tags(config, environment)
    log_retention_days = int(config.section("data")["log_retention_days"])

    stack = cdk.Stack(app, prefix, env=location)
    foundation = PatternFoundation(
        stack,
        "Foundation",
        pattern=config.name,
        environment=environment.name,
        log_retention_days=log_retention_days,
        secrets_prefix=environment.secrets_prefix,
        secret_names=SECRETS,
        rotation_days=environment.rotation_days,
    )
    topic = _alarm_topic(stack, prefix, environment)
    model = config.section("model")
    profile = AgentModelProfile(
        stack,
        "Model",
        prefix=prefix,
        team=str(model["team_tag"]),
        primary=str(model["primary"]),
        fallback=str(model.get("fallback") or ""),
        tags={"pattern": config.name, "environment": environment.name},
    )
    cdk.CfnOutput(stack, "RepositoryUri", value=foundation.repository.repository_uri)
    cdk.CfnOutput(stack, "LogGroupName", value=foundation.log_group.log_group_name)
    cdk.CfnOutput(stack, MODEL_PROFILE, value=profile.primary_arn)
    if profile.fallback is not None:
        cdk.CfnOutput(stack, FALLBACK_PROFILE, value=profile.fallback_arn)
    if environment.network_mode == "VPC":
        network_options = environment.network
        network = NetworkFoundation(
            stack,
            "Network",
            prefix=prefix,
            key=foundation.key,
            log_retention_days=log_retention_days,
            retain=environment.retain,
            nat_gateways=int(network_options.get("nat_gateways", 1)),
            allowed_domains=list(network_options.get("allowed_domains", ())),
            alarm_topic=topic,
            code_interpreter=bool(network_options.get("code_interpreter", False)),
        )
        cdk.CfnOutput(stack, NETWORK_SUBNETS, value=",".join(network.private_subnet_ids))
        cdk.CfnOutput(stack, NETWORK_SECURITY_GROUPS, value=network.runtime_security_group.security_group_id)
        cdk.CfnOutput(stack, NETWORK_VPC, value=network.vpc.vpc_id)
    for key, value in tags.items():
        cdk.Tags.of(stack).add(key, value)

    if runtime_arn:
        _edge(app, f"{prefix}-edge", location, config, environment, runtime_arn, front_door_policy, tags)
    return stack


def _alarm_topic(stack: cdk.Stack, prefix: str, environment: EnvironmentConfig) -> sns.Topic | None:
    if not environment.alarms:
        return None
    topic = sns.Topic(stack, "Alarms", topic_name=f"{prefix}-alarms", display_name=f"{prefix} alarms", enforce_ssl=True)
    # SNS mails a confirmation link; nothing is delivered until it is clicked.
    topic.add_subscription(subscriptions.EmailSubscription(environment.alarm_email))
    return topic


def _edge(
    app: cdk.App,
    name: str,
    location: cdk.Environment,
    config: PatternConfig,
    environment: EnvironmentConfig,
    runtime_arn: str,
    policy_file: str,
    tags: dict[str, str],
) -> cdk.Stack:
    if not policy_file:
        raise ValueError("the edge stack needs -c front_door_policy=<file from agentcore-kit front-door-policy>")
    policy = json.loads(Path(policy_file).read_text(encoding="utf-8"))
    if policy.get("runtime_arn") != runtime_arn:
        raise ValueError("front_door_policy was rendered for another runtime; re-run agentcore-kit front-door-policy")
    issuer, audience = os.environ.get("FRONT_DOOR_ISSUER", ""), os.environ.get("FRONT_DOOR_AUDIENCE", "")
    if not issuer or not audience:
        raise ValueError("set FRONT_DOOR_ISSUER and FRONT_DOOR_AUDIENCE (the sign-in token issuer and client id)")

    stack = cdk.Stack(app, name, env=location)
    prefix = name.removesuffix("-edge")
    key = kms.Key(stack, "Key", description=f"CMK for {prefix} front door tables and logs", enable_key_rotation=True)
    key.grant_encrypt_decrypt(cdk.aws_iam.ServicePrincipal(f"logs.{environment.region}.amazonaws.com"))
    rate, burst = environment.front_door_throttle
    door = FrontDoor(
        stack,
        "FrontDoor",
        prefix=prefix,
        key=key,
        retain=environment.retain,
        log_retention_days=int(config.section("data")["log_retention_days"]),
        agents=[policy],
        settings=environment.front_door,
        issuer=issuer,
        audience=audience,
        jwks_url=os.environ.get("FRONT_DOOR_JWKS_URL", ""),
        token_use=os.environ.get("FRONT_DOOR_TOKEN_USE", ""),
        image=image_asset(os.environ.get("BASE_LAMBDA_IMAGE", "")),
        throttle_rate=rate,
        throttle_burst=burst,
    )
    door.operator_policy()
    cdk.CfnOutput(stack, FRONT_DOOR_ROLE, value=door.role.role_arn)
    cdk.CfnOutput(stack, FRONT_DOOR_URL, value=door.url)
    if environment.alarms:
        topic = sns.Topic.from_topic_arn(
            stack,
            "AlarmTopic",
            stack.format_arn(service="sns", resource=f"{prefix}-alarms", arn_format=cdk.ArnFormat.NO_RESOURCE_NAME),
        )
        alarms = RuntimeAlarms(
            stack,
            "Alarms",
            prefix=prefix,
            owner=str(config.raw["owner"]),
            runbook_url=str(config.raw["runbook_url"]),
            topic=topic,
        )
        alarms.add_runtime(
            "runtime", runtime_arn=runtime_arn, runtime_name=config.runtime_name, endpoint=environment.endpoint
        )
        alarms.add_function("front-door-chat", door.chat_function, hint=f"/aws/lambda/{prefix}-front-door-chat")
        alarms.add_function("front-door-job", door.job_function, hint=f"/aws/lambda/{prefix}-front-door-job")
        alarms.add_http_api("front-door-api", door.api)
    for tag, value in tags.items():
        cdk.Tags.of(stack).add(tag, value)
    return stack


if __name__ == "__main__":
    application = cdk.App()
    build(
        application,
        str(application.node.try_get_context("env") or os.environ.get("CDK_ENV", "dev")),
        runtime_arn=str(application.node.try_get_context("runtime_arn") or ""),
        front_door_policy=str(application.node.try_get_context("front_door_policy") or ""),
    )
    application.synth()

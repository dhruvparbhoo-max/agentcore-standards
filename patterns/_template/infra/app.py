"""CDK app for the template's supporting resources. The AgentCore CLI deploys the runtime itself.

``cdk deploy -c env=dev`` creates the KMS key, the ECR repository, the masked
log group, and the pattern's secrets. ``make deploy`` then pushes the ARM64
image and runs ``agentcore deploy`` on the rendered project. ``make teardown``
destroys both, in reverse order.
"""

from __future__ import annotations

import os
from pathlib import Path

import aws_cdk as cdk
from agentcore_agent import load_pattern
from agentcore_agent.agentcore_json import pattern_tags, project_name
from agentcore_agent.environment import load_environment
from agentcore_constructs import PatternFoundation

PATTERN = Path(__file__).resolve().parents[1]
REPO = PATTERN.parents[1]
SECRETS: tuple[str, ...] = ()


def build(app: cdk.App, env_name: str) -> cdk.Stack:
    config = load_pattern(PATTERN)
    environment = load_environment(env_name, repo_root=REPO)
    stack = cdk.Stack(
        app,
        f"{project_name(config)}-{environment.name}",
        env=cdk.Environment(account=os.environ.get("CDK_DEFAULT_ACCOUNT"), region=environment.region),
    )
    foundation = PatternFoundation(
        stack,
        "Foundation",
        pattern=config.name,
        environment=environment.name,
        log_retention_days=int(config.section("data")["log_retention_days"]),
        secrets_prefix=environment.secrets_prefix,
        secret_names=SECRETS,
        rotation_days=environment.rotation_days,
    )
    for key, value in pattern_tags(config, environment).items():
        cdk.Tags.of(stack).add(key, value)
    cdk.CfnOutput(stack, "RepositoryUri", value=foundation.repository.repository_uri)
    cdk.CfnOutput(stack, "LogGroupName", value=foundation.log_group.log_group_name)
    return stack


if __name__ == "__main__":
    application = cdk.App()
    build(application, str(application.node.try_get_context("env") or os.environ.get("CDK_ENV", "dev")))
    application.synth()

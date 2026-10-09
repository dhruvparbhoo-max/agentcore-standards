"""The front door: two tables, one image, two functions, an HTTP API with a JWT authorizer.

The handlers and their environment are ``primitives/front-door``
(``agentcore_front_door.wiring``). Grants are least privilege:

- the state table (counters, leases, switches) gets Get/Put/Update/Delete/Query;
- the audit table gets ``PutItem`` and nothing else, and its resource policy
  denies every principal ``UpdateItem``, ``DeleteItem``, ``BatchWriteItem`` and
  the PartiQL writes, so no role can overwrite or delete an entry;
- ``InvokeAgentRuntime`` only on the runtimes this door fronts;
- on-behalf-of exchange only for the workload identities and credential
  providers the agent policies name.

The runtime resource policy that denies every other caller is applied by
``agentcore-kit harden`` with this construct's ``role`` ARN. Table shapes,
point-in-time recovery and RETAIN outside dev follow
aws-samples/sample-social-intelligence-agents ``infra/stacks/social_intelligence_stack.py``
(MIT-0). The API shape (HTTP API, JWT authorizer, one Lambda per route) follows
aws-samples/sample-agent-platform-with-agentcore (MIT-0). See docs/attribution/third-party.md.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import aws_cdk as cdk
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_apigatewayv2_authorizers as authorizers
from aws_cdk import aws_apigatewayv2_integrations as integrations
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

from agentcore_constructs.foundation import LOG_RETENTION

REPO_ROOT = Path(__file__).resolve().parents[4]
DOCKERFILE = "primitives/front-door/Dockerfile"
CHAT_HANDLER = "agentcore_front_door.handlers.chat.handler"
JOB_HANDLER = "agentcore_front_door.handlers.job.handler"
ASSET_EXCLUDE = [
    ".git",
    ".venv",
    "**/.venv",
    "**/__pycache__",
    "**/node_modules",
    "**/cdk.out",
    "build",
    "evidence",
    "frontend",
]
AUDIT_DENY = [
    "dynamodb:UpdateItem",
    "dynamodb:DeleteItem",
    "dynamodb:BatchWriteItem",
    "dynamodb:PartiQLUpdate",
    "dynamodb:PartiQLDelete",
]
STATE_ACTIONS = ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:Query"]
API_INTEGRATION_LIMIT_S = 29

ImageFor = Callable[[Construct, str], lambda_.DockerImageCode]


class FrontDoor(Construct):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        prefix: str,
        key: kms.IKey,
        retain: bool,
        log_retention_days: int,
        agents: Sequence[Mapping[str, Any]],
        settings: Mapping[str, Any],
        issuer: str,
        audience: str,
        jwks_url: str = "",
        token_use: str = "",
        claims: Mapping[str, str] | None = None,
        image: ImageFor | None = None,
        throttle_rate: int = 20,
        throttle_burst: int = 40,
        job_timeout_s: int = 900,
    ) -> None:
        super().__init__(scope, construct_id)
        if log_retention_days not in LOG_RETENTION:
            raise ValueError(f"log_retention_days must be one of {sorted(LOG_RETENTION)}")
        if not issuer or not audience:
            raise ValueError("issuer and audience are required: the front door only accepts verified callers")
        removal = cdk.RemovalPolicy.RETAIN if retain else cdk.RemovalPolicy.DESTROY
        self.prefix = prefix
        self.key = key
        self.agents = [dict(agent) for agent in agents]

        self.state_table = dynamodb.TableV2(
            self,
            "State",
            table_name=f"{prefix}-front-door-state",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            time_to_live_attribute="expires_at",
            encryption=dynamodb.TableEncryptionV2.customer_managed_key(key),
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            deletion_protection=retain,
            removal_policy=removal,
        )
        self.audit_table = dynamodb.TableV2(
            self,
            "Audit",
            table_name=f"{prefix}-front-door-audit",
            partition_key=dynamodb.Attribute(name="pk", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="sk", type=dynamodb.AttributeType.STRING),
            encryption=dynamodb.TableEncryptionV2.customer_managed_key(key),
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True
            ),
            deletion_protection=retain,
            removal_policy=removal,
            resource_policy=iam.PolicyDocument(
                statements=[
                    iam.PolicyStatement(
                        sid="AppendOnly",
                        effect=iam.Effect.DENY,
                        principals=[iam.AnyPrincipal()],
                        actions=AUDIT_DENY,
                        resources=["*"],
                    )
                ]
            ),
        )
        self.binding_secret = secretsmanager.Secret(
            self,
            "BindingSecret",
            secret_name=f"{prefix}/front-door/session-binding",
            description="HMAC key that binds session ids to callers",
            encryption_key=key,
            generate_secret_string=secretsmanager.SecretStringGenerator(password_length=64, exclude_punctuation=True),
            removal_policy=removal,
        )

        self.role = iam.Role(
            self,
            "Role",
            role_name=f"{prefix}-front-door"[:64],
            assumed_by=iam.ServicePrincipal("lambda.amazonaws.com"),
            description="Front door: the only principal allowed to start Runtime sessions",
        )
        self._grant()

        environment = {
            "FRONT_DOOR_STATE_TABLE": self.state_table.table_name,
            "FRONT_DOOR_AUDIT_TABLE": self.audit_table.table_name,
            "FRONT_DOOR_BINDING_SECRET_NAME": self.binding_secret.secret_name,
            "FRONT_DOOR_ISSUER": issuer,
            "FRONT_DOOR_AUDIENCE": audience,
            "FRONT_DOOR_JWKS_URL": jwks_url,
            "FRONT_DOOR_TOKEN_USE": token_use,
            "FRONT_DOOR_AGENTS": json.dumps(self.agents, separators=(",", ":"), sort_keys=True),
            "FRONT_DOOR_SETTINGS": json.dumps(dict(settings), separators=(",", ":"), sort_keys=True),
            **{f"FRONT_DOOR_CLAIM_{name.upper()}": claim for name, claim in (claims or {}).items()},
        }
        image_for = image or image_asset()
        retention = LOG_RETENTION[log_retention_days]
        self.chat_function = self._function(
            "Chat", image_for(self, CHAT_HANDLER), environment, retention, removal, timeout_s=API_INTEGRATION_LIMIT_S
        )
        self.job_function = self._function(
            "Job", image_for(self, JOB_HANDLER), environment, retention, removal, timeout_s=job_timeout_s
        )

        self.api = apigw.HttpApi(
            self,
            "Api",
            api_name=f"{prefix}-front-door",
            description="Chat and API callers. Long work is a job: this API times out at 30 seconds.",
            default_authorizer=authorizers.HttpJwtAuthorizer(
                "Jwt", issuer, jwt_audience=[audience], identity_source=["$request.header.Authorization"]
            ),
            create_default_stage=False,
        )
        self.api.add_routes(
            path="/agents/{agent}/invoke",
            methods=[apigw.HttpMethod.POST],
            integration=integrations.HttpLambdaIntegration("Chat", self.chat_function),
        )
        self.access_logs = logs.LogGroup(
            self, "AccessLogs", retention=retention, encryption_key=key, removal_policy=removal
        )
        self.stage = apigw.HttpStage(
            self,
            "Stage",
            http_api=self.api,
            stage_name="$default",
            auto_deploy=True,
            throttle=apigw.ThrottleSettings(rate_limit=throttle_rate, burst_limit=throttle_burst),
        )
        cfn_stage = self.stage.node.default_child
        assert isinstance(cfn_stage, apigw.CfnStage)
        cfn_stage.access_log_settings = apigw.CfnStage.AccessLogSettingsProperty(
            destination_arn=self.access_logs.log_group_arn,
            format=json.dumps(
                {
                    "requestId": "$context.requestId",
                    "routeKey": "$context.routeKey",
                    "status": "$context.status",
                    "sub": "$context.authorizer.claims.sub",
                    "latency": "$context.integrationLatency",
                }
            ),
        )

    @property
    def url(self) -> str:
        return self.stage.url

    def operator_policy(self) -> iam.ManagedPolicy:
        """For the people who flip kill switches and stop sessions: switch rows and ``StopRuntimeSession`` only."""
        return iam.ManagedPolicy(
            self,
            "OperatorPolicy",
            description="Kill switches and session stop for the front door",
            statements=[
                iam.PolicyStatement(
                    sid="SwitchRowsOnly",
                    actions=["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"],
                    resources=[self.state_table.table_arn],
                    conditions={"ForAllValues:StringEquals": {"dynamodb:LeadingKeys": ["switch"]}},
                ),
                iam.PolicyStatement(
                    sid="StopSessions",
                    actions=["bedrock-agentcore:StopRuntimeSession"],
                    resources=_runtime_resources(self.agents),
                ),
                iam.PolicyStatement(
                    actions=["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"], resources=[self.key.key_arn]
                ),
            ],
        )

    def grant_job_invoke(self, grantee: iam.IGrantable) -> None:
        """The triggers worker invokes the job function with IAM. Nothing else may."""
        self.job_function.grant_invoke(grantee)

    def _grant(self) -> None:
        self.role.add_managed_policy(
            iam.ManagedPolicy.from_aws_managed_policy_name("service-role/AWSLambdaBasicExecutionRole")
        )
        self.role.add_to_policy(
            iam.PolicyStatement(sid="StateTable", actions=STATE_ACTIONS, resources=[self.state_table.table_arn])
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="AuditAppendOnly", actions=["dynamodb:PutItem"], resources=[self.audit_table.table_arn]
            )
        )
        self.role.add_to_policy(
            iam.PolicyStatement(
                sid="TableKey",
                actions=["kms:Decrypt", "kms:Encrypt", "kms:GenerateDataKey"],
                resources=[self.key.key_arn],
            )
        )
        self.binding_secret.grant_read(self.role)
        runtimes = _runtime_resources(self.agents)
        if runtimes:
            self.role.add_to_policy(
                iam.PolicyStatement(
                    sid="InvokeFrontedRuntimes", actions=["bedrock-agentcore:InvokeAgentRuntime"], resources=runtimes
                )
            )
        stack = cdk.Stack.of(self)
        workloads = sorted({str(a["workload_name"]) for a in self.agents if a.get("obo") and a.get("workload_name")})
        providers = sorted({str(t["provider"]) for a in self.agents for t in a.get("obo", ())})
        if workloads and providers:
            base = f"arn:{stack.partition}:bedrock-agentcore:{stack.region}:{stack.account}"
            directory = f"{base}:workload-identity-directory/default"
            vault = f"{base}:token-vault/default"
            self.role.add_to_policy(
                iam.PolicyStatement(
                    sid="OnBehalfOfExchange",
                    actions=[
                        "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                        "bedrock-agentcore:GetResourceOauth2Token",
                    ],
                    resources=[
                        directory,
                        *(f"{directory}/workload-identity/{name}" for name in workloads),
                        vault,
                        *(f"{vault}/oauth2credentialprovider/{name}" for name in providers),
                    ],
                )
            )
            self.role.add_to_policy(
                iam.PolicyStatement(
                    sid="ProviderClientSecrets",
                    actions=["secretsmanager:GetSecretValue"],
                    resources=[
                        f"arn:{stack.partition}:secretsmanager:{stack.region}:{stack.account}:secret:"
                        f"bedrock-agentcore-identity!default/oauth2/{name}*"
                        for name in providers
                    ],
                )
            )

    def _function(
        self,
        name: str,
        code: lambda_.DockerImageCode,
        environment: Mapping[str, str],
        retention: logs.RetentionDays,
        removal: cdk.RemovalPolicy,
        *,
        timeout_s: int,
    ) -> lambda_.DockerImageFunction:
        log_group = logs.LogGroup(
            self,
            f"{name}Logs",
            log_group_name=f"/aws/lambda/{self.prefix}-front-door-{name.lower()}",
            retention=retention,
            encryption_key=self.key,
            removal_policy=removal,
        )
        return lambda_.DockerImageFunction(
            self,
            f"{name}Function",
            function_name=f"{self.prefix}-front-door-{name.lower()}"[:64],
            code=code,
            architecture=lambda_.Architecture.ARM_64,
            memory_size=512,
            timeout=cdk.Duration.seconds(timeout_s),
            role=self.role,
            environment=dict(environment),
            log_group=log_group,
            tracing=lambda_.Tracing.ACTIVE,
            description=f"Front door {name.lower()} handler",
        )


def image_asset(base_image: str = "") -> ImageFor:
    """The ``lambda-front-door`` image built from the repo root. Both handlers share one asset hash."""

    def build(_scope: Construct, handler: str) -> lambda_.DockerImageCode:
        return lambda_.DockerImageCode.from_image_asset(
            str(REPO_ROOT),
            file=DOCKERFILE,
            cmd=[handler],
            platform=cdk.aws_ecr_assets.Platform.LINUX_ARM64,
            build_args={"BASE_LAMBDA_IMAGE": base_image} if base_image else None,
            exclude=ASSET_EXCLUDE,
        )

    return build


def _runtime_resources(agents: Sequence[Mapping[str, Any]]) -> list[str]:
    arns = sorted({str(a["runtime_arn"]) for a in agents if str(a.get("runtime_arn", "")).startswith("arn:")})
    return [resource for arn in arns for resource in (arn, f"{arn}/runtime-endpoint/*")]

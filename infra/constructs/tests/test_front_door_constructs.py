from __future__ import annotations

import json
from typing import Any

import aws_cdk as cdk
import pytest
from agentcore_constructs import AgentModelProfile, FrontDoor, NetworkFoundation, RuntimeAlarms
from aws_cdk import assertions
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

ENV = cdk.Environment(account="111111111111", region="eu-west-2")
RUNTIME = "arn:" + "aws:bedrock-agentcore:eu-west-2:111111111111:runtime/demo-abc123"
AGENT: dict[str, Any] = {
    "agent": "demo",
    "team": "platform",
    "acts_as": "user",
    "endpoint": "PROD",
    "tools": ["lookup"],
    "max_turns": 20,
    "max_steps": 8,
    "timeout_s": 25,
    "session_id_min": 33,
    "max_usd_per_run": 0.5,
    "monthly_cap_usd": 50,
    "runtime_arn": RUNTIME,
    "workload_name": "demo-workload",
    "obo": [{"provider": "calendar", "scopes": ["calendar.read"]}],
}


def _stack() -> tuple[cdk.Stack, cdk.aws_kms.Key]:
    stack = cdk.Stack(cdk.App(), "Test", env=ENV)
    return stack, cdk.aws_kms.Key(stack, "Key", enable_key_rotation=True)


def _image(scope: Construct, handler: str) -> lambda_.DockerImageCode:
    repository = cdk.aws_ecr.Repository.from_repository_name(scope, f"Repo{handler.split('.')[-2]}", "front-door")
    return lambda_.DockerImageCode.from_ecr(repository, cmd=[handler])


def _door(*, retain: bool = True, agents: list[dict[str, Any]] | None = None) -> assertions.Template:
    stack, key = _stack()
    FrontDoor(
        stack,
        "Door",
        prefix="demo-prod",
        key=key,
        retain=retain,
        log_retention_days=90,
        agents=[AGENT] if agents is None else agents,
        settings={"quotas": {"user_daily": 100}},
        issuer="https://cognito-idp.eu-west-2.amazonaws.com/eu-west-2_example",
        audience="client-id",
        token_use="access",
        image=_image,
    )
    return assertions.Template.from_stack(stack)


def _statements(template: assertions.Template) -> list[dict[str, Any]]:
    return [
        statement
        for body in template.find_resources("AWS::IAM::Policy").values()
        for statement in body["Properties"]["PolicyDocument"]["Statement"]
    ]


def _actions(statement: dict[str, Any]) -> list[str]:
    action = statement["Action"]
    return [action] if isinstance(action, str) else list(action)


def test_audit_table_is_put_only_for_the_door() -> None:
    template = _door()
    audit = [s for s in _statements(template) if s.get("Sid") == "AuditAppendOnly"]
    assert len(audit) == 1
    assert _actions(audit[0]) == ["dynamodb:PutItem"]
    for statement in _statements(template):
        assert "dynamodb:*" not in _actions(statement)


def test_audit_table_denies_overwrite_and_delete_to_everyone() -> None:
    template = _door()
    tables = template.find_resources("AWS::DynamoDB::GlobalTable")
    audit = next(body for name, body in tables.items() if name.startswith("DoorAudit"))
    policy = audit["Properties"]["Replicas"][0]["ResourcePolicy"]["PolicyDocument"]["Statement"][0]
    assert policy["Effect"] == "Deny"
    assert policy["Principal"] == {"AWS": "*"}
    assert {"dynamodb:UpdateItem", "dynamodb:DeleteItem", "dynamodb:BatchWriteItem"} <= set(policy["Action"])


def test_tables_have_pitr_kms_and_ttl() -> None:
    template = _door()
    template.has_resource_properties(
        "AWS::DynamoDB::GlobalTable",
        {
            "TableName": "demo-prod-front-door-state",
            "TimeToLiveSpecification": {"AttributeName": "expires_at", "Enabled": True},
            "SSESpecification": assertions.Match.object_like({"SSEEnabled": True, "SSEType": "KMS"}),
            "Replicas": [
                assertions.Match.object_like(
                    {
                        "PointInTimeRecoverySpecification": {"PointInTimeRecoveryEnabled": True},
                        "DeletionProtectionEnabled": True,
                    }
                )
            ],
        },
    )


def test_dev_tables_can_be_destroyed() -> None:
    template = _door(retain=False)
    tables = template.find_resources("AWS::DynamoDB::GlobalTable")
    assert {body["DeletionPolicy"] for body in tables.values()} == {"Delete"}


def test_invoke_is_scoped_to_the_fronted_runtime() -> None:
    template = _door()
    invoke = next(s for s in _statements(template) if s.get("Sid") == "InvokeFrontedRuntimes")
    assert invoke["Action"] == "bedrock-agentcore:InvokeAgentRuntime"
    assert invoke["Resource"] == [RUNTIME, f"{RUNTIME}/runtime-endpoint/*"]


def test_on_behalf_of_is_scoped_to_named_workloads_and_providers() -> None:
    template = _door()
    obo = next(s for s in _statements(template) if s.get("Sid") == "OnBehalfOfExchange")
    text = json.dumps(obo["Resource"])
    assert "workload-identity/demo-workload" in text
    assert "oauth2credentialprovider/calendar" in text
    assert "*" not in text


def test_no_obo_grant_without_obo_targets() -> None:
    template = _door(agents=[{**AGENT, "obo": []}])
    assert not [s for s in _statements(template) if s.get("Sid") == "OnBehalfOfExchange"]


def test_http_api_has_jwt_authorizer_throttle_and_access_logs() -> None:
    template = _door()
    template.has_resource_properties(
        "AWS::ApiGatewayV2::Authorizer",
        {
            "AuthorizerType": "JWT",
            "JwtConfiguration": {
                "Audience": ["client-id"],
                "Issuer": "https://cognito-idp.eu-west-2.amazonaws.com/eu-west-2_example",
            },
        },
    )
    template.has_resource_properties(
        "AWS::ApiGatewayV2::Route", {"RouteKey": "POST /agents/{agent}/invoke", "AuthorizationType": "JWT"}
    )
    template.has_resource_properties(
        "AWS::ApiGatewayV2::Stage",
        {
            "DefaultRouteSettings": {"ThrottlingRateLimit": 20, "ThrottlingBurstLimit": 40},
            "AccessLogSettings": assertions.Match.object_like({"DestinationArn": assertions.Match.any_value()}),
        },
    )


def test_functions_are_arm64_with_the_wiring_environment() -> None:
    template = _door()
    functions = template.find_resources("AWS::Lambda::Function")
    assert len(functions) == 2
    for body in functions.values():
        props = body["Properties"]
        assert props["Architectures"] == ["arm64"]
        variables = props["Environment"]["Variables"]
        for name in ("FRONT_DOOR_STATE_TABLE", "FRONT_DOOR_AUDIT_TABLE", "FRONT_DOOR_BINDING_SECRET_NAME"):
            assert name in variables
        assert json.loads(variables["FRONT_DOOR_AGENTS"])[0]["agent"] == "demo"
    timeouts = sorted(body["Properties"]["Timeout"] for body in functions.values())
    assert timeouts == [29, 900]


def test_issuer_and_audience_are_required() -> None:
    stack, key = _stack()
    with pytest.raises(ValueError, match="issuer and audience"):
        FrontDoor(
            stack,
            "Door",
            prefix="p",
            key=key,
            retain=False,
            log_retention_days=30,
            agents=[],
            settings={},
            issuer="https://issuer",
            audience="",
            image=_image,
        )


def test_operator_policy_touches_switch_rows_only() -> None:
    stack, key = _stack()
    door = FrontDoor(
        stack,
        "Door",
        prefix="p",
        key=key,
        retain=False,
        log_retention_days=30,
        agents=[AGENT],
        settings={},
        issuer="https://issuer",
        audience="aud",
        image=_image,
    )
    door.operator_policy()
    template = assertions.Template.from_stack(stack)
    managed = template.find_resources("AWS::IAM::ManagedPolicy")
    statements = [s for body in managed.values() for s in body["Properties"]["PolicyDocument"]["Statement"]]
    rows = next(s for s in statements if s.get("Sid") == "SwitchRowsOnly")
    assert rows["Condition"] == {"ForAllValues:StringEquals": {"dynamodb:LeadingKeys": ["switch"]}}
    stop = next(s for s in statements if s.get("Sid") == "StopSessions")
    assert stop["Resource"][0] == RUNTIME


def _network(*, retain: bool = True, code_interpreter: bool = True, org_id: str = "") -> assertions.Template:
    stack, key = _stack()
    topic = cdk.aws_sns.Topic(stack, "Topic")
    NetworkFoundation(
        stack,
        "Net",
        prefix="demo-prod",
        key=key,
        log_retention_days=90,
        retain=retain,
        allowed_domains=["auth.example.com"],
        org_id=org_id,
        alarm_topic=topic,
        code_interpreter=code_interpreter,
    )
    return assertions.Template.from_stack(stack)


def test_runtime_security_group_is_https_egress_only() -> None:
    template = _network()
    template.has_resource_properties(
        "AWS::EC2::SecurityGroup",
        {
            "GroupDescription": "AgentCore runtime ENIs - HTTPS egress only",
            "SecurityGroupEgress": [
                assertions.Match.object_like({"FromPort": 443, "ToPort": 443, "IpProtocol": "tcp"})
            ],
        },
    )


def test_every_required_endpoint_exists() -> None:
    template = _network()
    names = json.dumps(template.find_resources("AWS::EC2::VPCEndpoint"))
    for service in (
        "bedrock-runtime",
        "bedrock-agent-runtime",
        "bedrock-agentcore",
        "bedrock-agentcore.gateway",
        "ssm",
        "secretsmanager",
        "logs",
        "ecr.api",
        "ecr.dkr",
        "xray",
        ".s3",
        ".dynamodb",
    ):
        assert f"{service}" in names, service


def test_org_scoped_policy_on_agentcore_endpoints() -> None:
    template = _network(org_id="o-example")
    endpoints = template.find_resources("AWS::EC2::VPCEndpoint")
    scoped = [body for body in endpoints.values() if "o-example" in json.dumps(body)]
    assert len(scoped) == 2


def test_dns_firewall_allows_aws_and_listed_names_then_blocks_everything() -> None:
    template = _network()
    lists = template.find_resources("AWS::Route53Resolver::FirewallDomainList")
    domains = sorted(tuple(body["Properties"]["Domains"]) for body in lists.values())
    assert ("*",) in domains
    allowed = next(d for d in domains if d != ("*",))
    assert "*.amazonaws.com" in allowed
    assert "auth.example.com" in allowed
    group = next(iter(template.find_resources("AWS::Route53Resolver::FirewallRuleGroup").values()))
    rules = sorted(group["Properties"]["FirewallRules"], key=lambda r: r["Priority"])
    assert [r["Action"] for r in rules] == ["ALLOW", "BLOCK"]
    template.has_resource_properties(
        "AWS::Route53Resolver::FirewallRuleGroupAssociation", {"MutationProtection": "ENABLED"}
    )
    template.resource_count_is("AWS::Route53Resolver::ResolverQueryLoggingConfigAssociation", 1)
    template.has_resource_properties(
        "AWS::CloudWatch::Alarm",
        {"AlarmDescription": assertions.Match.string_like_regexp("Check first"), "MetricName": "BlockedQueries"},
    )


def test_dev_firewall_can_be_torn_down() -> None:
    _network(retain=False).has_resource_properties(
        "AWS::Route53Resolver::FirewallRuleGroupAssociation", {"MutationProtection": "DISABLED"}
    )


def test_code_interpreter_runs_in_vpc_mode_with_its_own_role() -> None:
    template = _network()
    template.has_resource_properties(
        "AWS::BedrockAgentCore::CodeInterpreterCustom",
        {
            "NetworkConfiguration": {
                "NetworkMode": "VPC",
                "VpcConfig": {"SecurityGroups": assertions.Match.any_value(), "Subnets": assertions.Match.any_value()},
            },
            "ExecutionRoleArn": assertions.Match.any_value(),
        },
    )
    _network(code_interpreter=False).resource_count_is("AWS::BedrockAgentCore::CodeInterpreterCustom", 0)


def test_networking_parameters_are_published() -> None:
    template = _network()
    params = template.find_resources("AWS::SSM::Parameter")
    names = sorted(body["Properties"]["Name"] for body in params.values())
    assert names == [
        "/demo-prod/networking/private-subnet-ids",
        "/demo-prod/networking/runtime-security-group-id",
        "/demo-prod/networking/vpc-id",
    ]


def _alarms() -> assertions.Template:
    stack, _key = _stack()
    alarms = RuntimeAlarms(
        stack,
        "Alarms",
        prefix="demo-prod",
        owner="platform",
        runbook_url="https://example.invalid/runbook",
        alarm_email="ops@example.invalid",
    )
    alarms.add_runtime("runtime", runtime_arn=RUNTIME, runtime_name="demo_prod", endpoint="PROD")
    return assertions.Template.from_stack(stack)


def test_runtime_alarms_copy_the_enterprise_shape() -> None:
    template = _alarms()
    found = template.find_resources("AWS::CloudWatch::Alarm")
    by_metric = {body["Properties"]["MetricName"]: body["Properties"] for body in found.values()}
    assert set(by_metric) == {"SystemErrors", "Throttles", "Latency"}
    assert by_metric["SystemErrors"]["EvaluationPeriods"] == 2
    assert by_metric["Latency"]["ExtendedStatistic"] == "p99"
    assert by_metric["Latency"]["Threshold"] == 30_000
    for props in by_metric.values():
        assert props["Namespace"] == "AWS/Bedrock-AgentCore"
        assert props["TreatMissingData"] == "notBreaching"
        assert "Check first" in props["AlarmDescription"]
        assert "https://example.invalid/runbook" in props["AlarmDescription"]
        assert props["AlarmActions"] and props["OKActions"]
        dims = {d["Name"]: d["Value"] for d in props["Dimensions"]}
        assert dims == {"Resource": RUNTIME, "Operation": "InvokeAgentRuntime", "Name": "demo_prod::PROD"}
    template.has_resource_properties("AWS::SNS::Subscription", {"Protocol": "email", "Endpoint": "ops@example.invalid"})
    template.resource_count_is("AWS::CloudWatch::Dashboard", 1)


def test_alarms_require_a_runbook() -> None:
    stack, _ = _stack()
    with pytest.raises(ValueError, match="runbook_url"):
        RuntimeAlarms(stack, "Alarms", prefix="p", owner="o", runbook_url="")


def test_front_door_functions_and_api_get_alarms() -> None:
    stack, key = _stack()
    door = FrontDoor(
        stack,
        "Door",
        prefix="p",
        key=key,
        retain=False,
        log_retention_days=30,
        agents=[AGENT],
        settings={},
        issuer="https://issuer",
        audience="aud",
        image=_image,
    )
    alarms = RuntimeAlarms(stack, "Alarms", prefix="p", owner="o", runbook_url="https://example.invalid/r")
    alarms.add_function("front-door-chat", door.chat_function, hint="the chat function logs")
    alarms.add_http_api("front-door-api", door.api)
    names = sorted(alarms.alarms)
    assert names == ["front-door-api-5xx", "front-door-chat-errors", "front-door-chat-throttles"]


def test_model_profiles_copy_geographic_profiles_with_team_tag() -> None:
    stack, _ = _stack()
    role = cdk.aws_iam.Role(stack, "Agent", assumed_by=cdk.aws_iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"))
    profile = AgentModelProfile(
        stack,
        "Model",
        prefix="demo-prod",
        team="platform",
        primary="eu.anthropic.claude-sonnet-4-5-20250929-v1:0",
        fallback="eu.anthropic.claude-haiku-4-5-20251001-v1:0",
        tags={"pattern": "demo"},
    )
    profile.grant_invoke(role)
    template = assertions.Template.from_stack(stack)
    profiles = template.find_resources("AWS::Bedrock::ApplicationInferenceProfile")
    assert len(profiles) == 2
    for body in profiles.values():
        props = body["Properties"]
        assert {"Key": "team", "Value": "platform"} in props["Tags"]
        assert "inference-profile/eu.anthropic" in json.dumps(props["ModelSource"])
    statements = _statements(template)
    assert any("Condition" in s and "bedrock:InferenceProfileArn" in json.dumps(s["Condition"]) for s in statements)


def test_model_profile_refuses_a_bare_model_id() -> None:
    stack, _ = _stack()
    with pytest.raises(ValueError, match="geographic inference profile"):
        AgentModelProfile(stack, "Model", prefix="p", team="t", primary="anthropic.claude-3-haiku")

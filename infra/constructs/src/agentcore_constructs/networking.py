"""Network lockdown for VPC-mode runtimes: private subnets, endpoints, DNS Firewall, Code Interpreter in VPC mode.

Sources (docs/attribution/third-party.md):

- Private-with-egress subnets, a runtime security group with no inbound rules
  and 443 egress only, interface endpoints for Bedrock, ECR, ECR Docker, Logs and
  Secrets Manager, the S3 gateway endpoint, the AgentCore gateway endpoint with an
  org-scoped policy, and the SSM parameters for vpc/subnets/security group:
  aws-samples/sample-agentcore-enterprise-platform ``stacks/networking_stack.py`` (Apache-2.0).
- The full endpoint list (bedrock-runtime, bedrock-agent-runtime, bedrock-agentcore,
  bedrock-agentcore.gateway, ssm, secretsmanager, logs, ecr.api, ecr.dkr, xray,
  S3 and DynamoDB gateways): awslabs/fullstack-solution-template-for-agentcore
  ``docs/DEPLOYMENT.md`` (Apache-2.0).
- ``CfnFirewallDomainList``, ``CfnFirewallRuleGroup``, ``CfnFirewallRuleGroupAssociation``
  with mutation protection, query logging, and a blocked-queries metric filter and
  alarm: aws-samples/sample-route53-iac-with-cdk ``examples/dns_firewall_example.py`` (MIT-0).
  The sample blocks named bad domains; here the rule group is an allow-list
  followed by a block of everything else, because DNS lookups have been used to
  move data out of sandboxes.
- Code Interpreter in VPC mode with its own role: ``AWS::BedrockAgentCore::CodeInterpreterCustom``
  (CloudFormation reference); the requirement is docs/design/library.md "Code the model wrote".
"""

from __future__ import annotations

from collections.abc import Sequence

import aws_cdk as cdk
from aws_cdk import aws_bedrockagentcore as agentcore
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_kms as kms
from aws_cdk import aws_logs as logs
from aws_cdk import aws_route53resolver as resolver
from aws_cdk import aws_sns as sns
from aws_cdk import aws_ssm as ssm
from constructs import Construct

from agentcore_constructs.foundation import LOG_RETENTION

AWS_DOMAINS: tuple[str, ...] = ("amazonaws.com", "*.amazonaws.com", "api.aws", "*.api.aws", "*.internal")
INTERFACE_ENDPOINTS: tuple[tuple[str, ec2.InterfaceVpcEndpointAwsService], ...] = (
    ("BedrockRuntime", ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME),
    ("BedrockAgentRuntime", ec2.InterfaceVpcEndpointAwsService.BEDROCK_AGENT_RUNTIME),
    ("AgentCore", ec2.InterfaceVpcEndpointAwsService.BEDROCK_AGENTCORE),
    ("AgentCoreGateway", ec2.InterfaceVpcEndpointAwsService.BEDROCK_AGENTCORE_GATEWAY),
    ("Ssm", ec2.InterfaceVpcEndpointAwsService.SSM),
    ("SecretsManager", ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER),
    ("Logs", ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS),
    ("EcrApi", ec2.InterfaceVpcEndpointAwsService.ECR),
    ("EcrDocker", ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER),
    ("XRay", ec2.InterfaceVpcEndpointAwsService.XRAY),
)
ORG_SCOPED = ("AgentCore", "AgentCoreGateway")


class NetworkFoundation(Construct):
    """One VPC per pattern environment. ``network_config`` is what ``agentcore.json`` needs for VPC mode."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        prefix: str,
        key: kms.IKey,
        log_retention_days: int,
        retain: bool,
        cidr: str = "10.0.0.0/16",
        nat_gateways: int = 1,
        allowed_domains: Sequence[str] = (),
        org_id: str = "",
        alarm_topic: sns.ITopic | None = None,
        code_interpreter: bool = False,
    ) -> None:
        super().__init__(scope, construct_id)
        if log_retention_days not in LOG_RETENTION:
            raise ValueError(f"log_retention_days must be one of {sorted(LOG_RETENTION)}")
        removal = cdk.RemovalPolicy.RETAIN if retain else cdk.RemovalPolicy.DESTROY
        self.prefix = prefix

        # A NAT gateway is needed only for public endpoints with no VPC endpoint
        # (for example a Cognito hosted domain); the DNS Firewall still decides
        # which names resolve.
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            vpc_name=f"{prefix}-vpc",
            ip_addresses=ec2.IpAddresses.cidr(cidr),
            max_azs=2,
            nat_gateways=nat_gateways,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="Public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                ec2.SubnetConfiguration(name="Private", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, cidr_mask=24),
            ],
        )
        # No inbound rules: callers reach the runtime through the AgentCore data
        # plane, not the VPC. EC2 rejects a non-ASCII GroupDescription.
        self.runtime_security_group = ec2.SecurityGroup(
            self,
            "RuntimeSecurityGroup",
            vpc=self.vpc,
            security_group_name=f"{prefix}-runtime-sg",
            description="AgentCore runtime ENIs - HTTPS egress only",
            allow_all_outbound=False,
        )
        self.runtime_security_group.add_egress_rule(
            ec2.Peer.any_ipv4(), ec2.Port.tcp(443), "HTTPS to AWS service endpoints and NAT egress"
        )

        self.endpoints: dict[str, ec2.InterfaceVpcEndpoint] = {}
        for name, service in INTERFACE_ENDPOINTS:
            self.endpoints[name] = self.vpc.add_interface_endpoint(f"{name}Endpoint", service=service)
        self.vpc.add_gateway_endpoint("S3Endpoint", service=ec2.GatewayVpcEndpointAwsService.S3)
        self.vpc.add_gateway_endpoint("DynamoDbEndpoint", service=ec2.GatewayVpcEndpointAwsService.DYNAMODB)
        if org_id:
            for name in ORG_SCOPED:
                self.endpoints[name].add_to_policy(
                    iam.PolicyStatement(
                        sid="OnlyThisOrganization",
                        principals=[iam.AnyPrincipal()],
                        actions=["bedrock-agentcore:*"],
                        resources=["*"],
                        conditions={"StringEquals": {"aws:PrincipalOrgID": org_id}},
                    )
                )

        self.private_subnet_ids = self.vpc.select_subnets(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS).subnet_ids
        self._dns_firewall(
            prefix=prefix,
            key=key,
            retention=LOG_RETENTION[log_retention_days],
            removal=removal,
            mutation_protection=retain,
            domains=[*AWS_DOMAINS, *allowed_domains],
            alarm_topic=alarm_topic,
        )

        self.code_interpreter: agentcore.CfnCodeInterpreterCustom | None = None
        self.code_interpreter_role: iam.Role | None = None
        if code_interpreter:
            self._code_interpreter(prefix)

        for name, value in (
            ("vpc-id", self.vpc.vpc_id),
            ("private-subnet-ids", ",".join(self.private_subnet_ids)),
            ("runtime-security-group-id", self.runtime_security_group.security_group_id),
        ):
            ssm.StringParameter(
                self, f"Param{_logical(name)}", parameter_name=f"/{prefix}/networking/{name}", string_value=value
            )

    @property
    def network_config(self) -> dict[str, object]:
        """The ``networkConfig`` block for a Container runtime in VPC mode. CodeBuild needs ``vpcId``."""
        return {
            "subnets": self.private_subnet_ids,
            "securityGroups": [self.runtime_security_group.security_group_id],
            "vpcId": self.vpc.vpc_id,
        }

    def _dns_firewall(
        self,
        *,
        prefix: str,
        key: kms.IKey,
        retention: logs.RetentionDays,
        removal: cdk.RemovalPolicy,
        mutation_protection: bool,
        domains: Sequence[str],
        alarm_topic: sns.ITopic | None,
    ) -> None:
        query_log_name = f"/agentcore/{prefix}/dns-queries"
        self.query_log_group = logs.LogGroup(
            self,
            "DnsQueryLogs",
            log_group_name=query_log_name,
            retention=retention,
            encryption_key=key,
            removal_policy=removal,
        )
        query_logging = resolver.CfnResolverQueryLoggingConfig(
            self, "QueryLogging", name=f"{prefix}-dns-queries", destination_arn=self.query_log_group.log_group_arn
        )
        resolver.CfnResolverQueryLoggingConfigAssociation(
            self,
            "QueryLoggingAssociation",
            resolver_query_log_config_id=query_logging.attr_id,
            resource_id=self.vpc.vpc_id,
        )
        allowed = resolver.CfnFirewallDomainList(
            self, "AllowedDomains", name=f"{prefix}-allowed", domains=sorted(set(domains))
        )
        everything = resolver.CfnFirewallDomainList(self, "EverythingElse", name=f"{prefix}-everything", domains=["*"])
        self.firewall_rule_group = resolver.CfnFirewallRuleGroup(
            self,
            "FirewallRules",
            name=f"{prefix}-egress",
            firewall_rules=[
                resolver.CfnFirewallRuleGroup.FirewallRuleProperty(
                    action="ALLOW", firewall_domain_list_id=allowed.attr_id, priority=100
                ),
                resolver.CfnFirewallRuleGroup.FirewallRuleProperty(
                    action="BLOCK", firewall_domain_list_id=everything.attr_id, priority=200, block_response="NXDOMAIN"
                ),
            ],
        )
        # Mutation protection stops anyone removing the association by hand. It
        # also stops CloudFormation, so a destroyable dev stack leaves it off.
        resolver.CfnFirewallRuleGroupAssociation(
            self,
            "FirewallAssociation",
            name=f"{prefix}-egress",
            firewall_rule_group_id=self.firewall_rule_group.attr_id,
            vpc_id=self.vpc.vpc_id,
            priority=101,
            mutation_protection="ENABLED" if mutation_protection else "DISABLED",
        )
        logs.MetricFilter(
            self,
            "BlockedQueriesFilter",
            log_group=self.query_log_group,
            metric_namespace="AgentCore/DnsFirewall",
            metric_name="BlockedQueries",
            filter_pattern=logs.FilterPattern.literal('"firewall_rule_action":"BLOCK"'),
            metric_value="1",
            default_value=0,
        )
        if alarm_topic is not None:
            alarm = cloudwatch.Alarm(
                self,
                "BlockedQueriesAlarm",
                alarm_name=f"{prefix}-dns-blocked",
                metric=cloudwatch.Metric(
                    namespace="AgentCore/DnsFirewall",
                    metric_name="BlockedQueries",
                    statistic="Sum",
                    period=cdk.Duration.minutes(5),
                ),
                threshold=0,
                evaluation_periods=1,
                comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
                treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
                alarm_description=(
                    f"A name outside the allow-list was looked up from {prefix}. Check first: "
                    f"the query_name in {query_log_name}; a new dependency "
                    "belongs in network.allowed_domains, anything else is an exfiltration attempt."
                ),
            )
            alarm.add_alarm_action(cw_actions.SnsAction(alarm_topic))

    def _code_interpreter(self, prefix: str) -> None:
        self.code_interpreter_role = iam.Role(
            self,
            "CodeInterpreterRole",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            description="Code Interpreter sessions: holds only what one run needs; grant per pattern",
        )
        self.code_interpreter = agentcore.CfnCodeInterpreterCustom(
            self,
            "CodeInterpreter",
            name=_agentcore_name(f"{prefix}_code"),
            description="Model-written code runs here, in VPC mode behind the DNS Firewall",
            execution_role_arn=self.code_interpreter_role.role_arn,
            network_configuration=agentcore.CfnCodeInterpreterCustom.CodeInterpreterNetworkConfigurationProperty(
                network_mode="VPC",
                vpc_config=agentcore.CfnCodeInterpreterCustom.VpcConfigProperty(
                    security_groups=[self.runtime_security_group.security_group_id],
                    subnets=self.private_subnet_ids,
                ),
            ),
        )


def _agentcore_name(text: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in text)[:48]


def _logical(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in name.split("-") if part)

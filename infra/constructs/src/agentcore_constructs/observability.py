"""Alarms per runtime with "Check first" hints, one SNS topic, and a dashboard.

Source: aws-samples/sample-agentcore-enterprise-platform ``stacks/observability_stack.py``
(lines 204 to 370, Apache-2.0; docs/attribution/third-party.md). Copied: the SNS
topic with an email subscription; SystemErrors over two periods, Throttles, and
p99 Latency over three periods in ``AWS/Bedrock-AgentCore`` with the
``Resource``/``Operation``/``Name`` dimensions; alarm and OK actions both to the
topic; missing data treated as not breaching; a dashboard row per runtime.
Added: every description ends with the pattern's runbook and owner, and the
front door's Lambda functions and HTTP API get the same treatment.
"""

from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import aws_apigatewayv2 as apigw
from aws_cdk import aws_cloudwatch as cloudwatch
from aws_cdk import aws_cloudwatch_actions as cw_actions
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_sns as sns
from aws_cdk import aws_sns_subscriptions as subscriptions
from constructs import Construct

NAMESPACE = "AWS/Bedrock-AgentCore"
FIVE_MINUTES = cdk.Duration.minutes(5)


class RuntimeAlarms(Construct):
    """``add_runtime`` once per runtime endpoint; ``add_function`` and ``add_http_api`` for the front door."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        prefix: str,
        owner: str,
        runbook_url: str,
        alarm_email: str = "",
        topic: sns.ITopic | None = None,
    ) -> None:
        super().__init__(scope, construct_id)
        if not runbook_url:
            raise ValueError("runbook_url is required: every alarm names the runbook")
        self.prefix = prefix
        self.footer = f" Runbook: {runbook_url} Owner: {owner}."
        if topic is None:
            created = sns.Topic(
                self, "Topic", topic_name=f"{prefix}-alarms", display_name=f"{prefix} alarms", enforce_ssl=True
            )
            if alarm_email:
                # SNS mails a confirmation link; nothing is delivered until it is clicked.
                created.add_subscription(subscriptions.EmailSubscription(alarm_email))
            topic = created
        self.topic = topic
        self.alarms: dict[str, cloudwatch.Alarm] = {}
        self.dashboard = cloudwatch.Dashboard(self, "Dashboard", dashboard_name=f"{prefix}-ops")
        self.dashboard.add_widgets(cloudwatch.TextWidget(markdown=f"# {prefix}\n{self.footer.strip()}", width=24))

    def add_runtime(
        self,
        key: str,
        *,
        runtime_arn: str,
        runtime_name: str,
        endpoint: str,
        latency_p99_ms: int = 30_000,
        log_group_name: str = "",
    ) -> None:
        dims = {"Resource": runtime_arn, "Operation": "InvokeAgentRuntime", "Name": f"{runtime_name}::{endpoint}"}
        logs_hint = log_group_name or f"/aws/bedrock-agentcore/runtimes/{runtime_name}"
        self._alarm(
            f"{key}-system-errors",
            _metric("SystemErrors", dims),
            f"AgentCore-side failures in {key} across two consecutive periods. Check first: {logs_hint}.",
            evaluation_periods=2,
        )
        self._alarm(
            f"{key}-throttles",
            _metric("Throttles", dims),
            f"InvokeAgentRuntime on {key} is being throttled. Check first: concurrent sessions "
            "against the AgentCore runtime quota, then the front door quotas.",
        )
        self._alarm(
            f"{key}-latency-p99",
            _metric("Latency", dims, "p99"),
            f"{key} p99 latency above {latency_p99_ms // 1000}s for 15 minutes. Check first: the slow trace "
            "in CloudWatch Transaction Search, then model throttling on the fallback profile.",
            threshold=latency_p99_ms,
            evaluation_periods=3,
            datapoints_to_alarm=3,
        )
        self.dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title=f"{key} traffic",
                left=[_metric("Invocations", dims), _metric("Sessions", dims)],
                width=8,
            ),
            cloudwatch.GraphWidget(
                title=f"{key} errors",
                left=[_metric("SystemErrors", dims), _metric("UserErrors", dims), _metric("Throttles", dims)],
                stacked=True,
                width=8,
            ),
            cloudwatch.GraphWidget(
                title=f"{key} latency",
                left=[_metric("Latency", dims, "p99", "p99"), _metric("Latency", dims, "p50", "p50")],
                width=8,
            ),
        )

    def add_function(self, key: str, function: lambda_.IFunction, *, hint: str) -> None:
        errors = function.metric_errors(period=FIVE_MINUTES, statistic="Sum")
        throttles = function.metric_throttles(period=FIVE_MINUTES, statistic="Sum")
        self._alarm(
            f"{key}-errors",
            errors,
            f"{key} raised errors in two consecutive periods. Check first: {hint}.",
            evaluation_periods=2,
        )
        self._alarm(
            f"{key}-throttles",
            throttles,
            f"{key} is being throttled. Check first: the account's Lambda concurrency and reserved concurrency.",
        )
        self.dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title=f"{key}",
                left=[function.metric_invocations(period=FIVE_MINUTES, statistic="Sum"), errors, throttles],
                width=12,
            ),
            cloudwatch.GraphWidget(
                title=f"{key} duration",
                left=[function.metric_duration(period=FIVE_MINUTES, statistic="p99")],
                width=12,
            ),
        )

    def add_http_api(self, key: str, api: apigw.IHttpApi) -> None:
        server = api.metric_server_error(period=FIVE_MINUTES, statistic="Sum")
        client = api.metric_client_error(period=FIVE_MINUTES, statistic="Sum")
        self._alarm(
            f"{key}-5xx",
            server,
            f"{key} returned 5xx in two consecutive periods. Check first: the front door chat Lambda logs; "
            "a 503 after 30 seconds is the HTTP API integration timeout, and long work belongs on a job.",
            evaluation_periods=2,
        )
        self.dashboard.add_widgets(
            cloudwatch.GraphWidget(
                title=f"{key} responses",
                left=[api.metric_count(period=FIVE_MINUTES, statistic="Sum"), client, server],
                width=24,
            )
        )

    def _alarm(
        self,
        name: str,
        metric: cloudwatch.IMetric,
        description: str,
        *,
        threshold: float = 0,
        evaluation_periods: int = 1,
        datapoints_to_alarm: int | None = None,
    ) -> None:
        alarm = cloudwatch.Alarm(
            self,
            f"Alarm-{name}",
            alarm_name=f"{self.prefix}-{name}",
            metric=metric,
            threshold=threshold,
            evaluation_periods=evaluation_periods,
            datapoints_to_alarm=datapoints_to_alarm,
            comparison_operator=cloudwatch.ComparisonOperator.GREATER_THAN_THRESHOLD,
            # Error metrics only emit when nonzero, so missing data is good news.
            treat_missing_data=cloudwatch.TreatMissingData.NOT_BREACHING,
            alarm_description=description + self.footer,
        )
        alarm.add_alarm_action(cw_actions.SnsAction(self.topic))
        alarm.add_ok_action(cw_actions.SnsAction(self.topic))
        self.alarms[name] = alarm


def _metric(name: str, dims: dict[str, str], stat: str = "Sum", label: str | None = None) -> cloudwatch.Metric:
    return cloudwatch.Metric(
        namespace=NAMESPACE, metric_name=name, dimensions_map=dims, statistic=stat, period=FIVE_MINUTES, label=label
    )

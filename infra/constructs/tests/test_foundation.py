from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import aws_cdk as cdk
import pytest
from agentcore_constructs import PatternFoundation, RotationFunction, removal_for
from aws_cdk import assertions

ENV = cdk.Environment(account="111111111111", region="eu-west-2")


def _synth(environment: str, *, rotate: bool = False, retention: int = 90) -> assertions.Template:
    app = cdk.App()
    stack = cdk.Stack(app, "Test", env=ENV)
    rotation = None
    if rotate:
        key = cdk.aws_kms.Key(stack, "RotationKey", enable_key_rotation=True)
        rotation = RotationFunction(stack, "Rotation", key=key).function
    foundation = PatternFoundation(
        stack,
        "Foundation",
        pattern="_template",
        environment=environment,
        log_retention_days=retention,
        secrets_prefix=f"agentcore/{environment}",
        secret_names=["webhook-signing-key"],
        rotation_days=30,
        rotation_function=rotation,
        custom_identifiers={"EmployeeId": r"EMP-\d{6}"},
    )
    role = cdk.aws_iam.Role(stack, "ToolRole", assumed_by=cdk.aws_iam.ServicePrincipal("lambda.amazonaws.com"))
    foundation.grant_secret_read("webhook-signing-key", role)
    foundation.unmask_policies()
    return assertions.Template.from_stack(stack)


def test_kms_key_rotates() -> None:
    _synth("dev").has_resource_properties("AWS::KMS::Key", {"EnableKeyRotation": True})


def test_ecr_scans_on_push_and_keeps_ten() -> None:
    template = _synth("dev")
    template.has_resource_properties(
        "AWS::ECR::Repository",
        {
            "ImageScanningConfiguration": {"ScanOnPush": True},
            "ImageTagMutability": "IMMUTABLE",
            "LifecyclePolicy": assertions.Match.object_like(
                {"LifecyclePolicyText": assertions.Match.string_like_regexp('"countNumber":10')}
            ),
        },
    )


def test_log_group_has_retention_and_pii_masking() -> None:
    template = _synth("prod", retention=365)
    template.has_resource_properties(
        "AWS::Logs::LogGroup",
        {"RetentionInDays": 365, "DataProtectionPolicy": assertions.Match.any_value()},
    )
    groups: dict[str, Any] = template.find_resources("AWS::Logs::LogGroup")
    policy = next(iter(groups.values()))["Properties"]["DataProtectionPolicy"]
    text = str(policy)
    assert "EmailAddress" in text
    assert "IpAddress" in text
    assert "EmployeeId" in text


def test_dev_destroys_and_prod_retains() -> None:
    assert removal_for("dev") == cdk.RemovalPolicy.DESTROY
    assert removal_for("prod") == cdk.RemovalPolicy.RETAIN
    _synth("dev").has_resource("AWS::SecretsManager::Secret", {"DeletionPolicy": "Delete"})
    _synth("prod").has_resource("AWS::SecretsManager::Secret", {"DeletionPolicy": "Retain"})


def test_secret_rotation_schedule() -> None:
    _synth("prod", rotate=True).has_resource_properties(
        "AWS::SecretsManager::RotationSchedule",
        {"RotationRules": {"ScheduleExpression": "rate(30 days)"}},
    )


def test_only_the_tool_role_reads_the_secret() -> None:
    template = _synth("dev")
    policies = template.find_resources("AWS::IAM::Policy")
    readers = [
        name
        for name, body in policies.items()
        if "secretsmanager:GetSecretValue" in str(body["Properties"]["PolicyDocument"])
    ]
    assert len(readers) == 1
    assert readers[0].startswith("ToolRole")


def test_unmask_is_scoped_to_the_log_group() -> None:
    template = _synth("dev")
    managed = template.find_resources("AWS::IAM::ManagedPolicy")
    effects = sorted(
        statement["Effect"]
        for body in managed.values()
        for statement in body["Properties"]["PolicyDocument"]["Statement"]
        if statement["Action"] == "logs:Unmask"
    )
    assert effects == ["Allow", "Deny"]
    for body in managed.values():
        for statement in body["Properties"]["PolicyDocument"]["Statement"]:
            assert statement["Resource"] != "*"


def test_bad_retention_is_refused() -> None:
    with pytest.raises(ValueError, match="log_retention_days"):
        _synth("dev", retention=14)


class _Exceptions:
    class ResourceNotFoundException(Exception):
        pass


class FakeSecrets:
    exceptions = _Exceptions

    def __init__(self) -> None:
        self.stages = {"v1": ["AWSCURRENT"], "v2": ["AWSPENDING"]}
        self.values = {"v1": "old"}

    def describe_secret(self, SecretId: str) -> dict[str, Any]:
        return {"RotationEnabled": True, "VersionIdsToStages": self.stages}

    def get_secret_value(self, SecretId: str, VersionStage: str, VersionId: str | None = None) -> dict[str, Any]:
        if VersionId is not None and VersionId not in self.values:
            raise _Exceptions.ResourceNotFoundException()
        return {"SecretString": self.values.get(VersionId or "v1", "")}

    def put_secret_value(self, SecretId: str, ClientRequestToken: str, SecretString: str, VersionStages: list[str]):  # type: ignore[no-untyped-def]
        self.values[ClientRequestToken] = SecretString

    def update_secret_version_stage(
        self, SecretId: str, VersionStage: str, MoveToVersionId: str, RemoveFromVersionId: str
    ):  # type: ignore[no-untyped-def]
        self.stages = {MoveToVersionId: ["AWSCURRENT"], RemoveFromVersionId: []}


def _rotation_module() -> Any:
    path = Path(__file__).resolve().parents[2] / "rotation" / "handler.py"
    spec = importlib.util.spec_from_file_location("rotation_handler", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rotation_steps_issue_and_promote_a_new_value() -> None:
    rotation = _rotation_module()
    client = FakeSecrets()
    for step in ("createSecret", "setSecret", "testSecret", "finishSecret"):
        rotation.handler({"SecretId": "s", "ClientRequestToken": "v2", "Step": step}, None, client=client)
    assert client.values["v2"] != "old"
    assert client.stages["v2"] == ["AWSCURRENT"]

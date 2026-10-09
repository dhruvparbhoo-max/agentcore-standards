"""Each agent's own model key: an application inference profile per model, tagged with the team.

The profile copies a system geographic profile (``eu.``, ``us.``, ``apac.``,
``global.``), so requests keep the geography the pattern names while cost and
throttling are attributed to this agent. No reference repo creates application
inference profiles; the shape follows the Bedrock user guide, "Create an
application inference profile" (``AWS::Bedrock::ApplicationInferenceProfile``,
``ModelSource.CopyFrom``). The team tag is in the spirit of awslabs/loom's group
tag (docs/design/library.md, "Front door" step 8).
"""

from __future__ import annotations

from collections.abc import Mapping

import aws_cdk as cdk
from aws_cdk import aws_bedrock as bedrock
from aws_cdk import aws_iam as iam
from constructs import Construct

GEOGRAPHIES = ("eu.", "us.", "apac.", "global.")


class AgentModelProfile(Construct):
    """``primary_arn`` and ``fallback_arn`` reach the runtime as ``AGENTCORE_MODEL_PROFILE_ARN`` and its fallback."""

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        prefix: str,
        team: str,
        primary: str,
        fallback: str = "",
        tags: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(scope, construct_id)
        all_tags = {**(tags or {}), "team": team}
        self.primary = self._profile("Primary", f"{prefix}-primary", primary, all_tags)
        self.fallback = self._profile("Fallback", f"{prefix}-fallback", fallback, all_tags) if fallback else None

    @property
    def primary_arn(self) -> str:
        return self.primary.attr_inference_profile_arn

    @property
    def fallback_arn(self) -> str:
        return self.fallback.attr_inference_profile_arn if self.fallback is not None else ""

    def grant_invoke(self, grantee: iam.IGrantable) -> None:
        """Invoke through this agent's profiles only. The profile's underlying models are matched by ARN."""
        profiles = [self.primary_arn] + ([self.fallback_arn] if self.fallback is not None else [])
        iam.Grant.add_to_principal(
            grantee=grantee,
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resource_arns=profiles,
        )
        iam.Grant.add_to_principal(
            grantee=grantee,
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resource_arns=["arn:" + "aws:bedrock:*::foundation-model/*"],
            conditions={"StringLike": {"bedrock:InferenceProfileArn": profiles}},
        )

    def _profile(
        self, construct_id: str, name: str, source: str, tags: Mapping[str, str]
    ) -> bedrock.CfnApplicationInferenceProfile:
        if not source.startswith(GEOGRAPHIES):
            raise ValueError(f"{source!r} is not a geographic inference profile id ({', '.join(GEOGRAPHIES)})")
        stack = cdk.Stack.of(self)
        return bedrock.CfnApplicationInferenceProfile(
            self,
            construct_id,
            inference_profile_name=name[:64],
            description=f"{name}: per-agent key for cost and throttling",
            model_source=bedrock.CfnApplicationInferenceProfile.InferenceProfileModelSourceProperty(
                copy_from=stack.format_arn(
                    service="bedrock",
                    resource="inference-profile",
                    resource_name=source,
                    arn_format=cdk.ArnFormat.SLASH_RESOURCE_NAME,
                ),
            ),
            tags=[cdk.CfnTag(key=k, value=v) for k, v in sorted(tags.items())],
        )

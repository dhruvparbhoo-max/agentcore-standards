"""End to end on a deployed runtime. Skipped unless the deploy settings are in the environment.

Run after ``make deploy PATTERN=ambient``. Nothing here has been run against AWS.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import pytest
from agentcore_agent.config import ACTOR_HEADER

REQUIRED = ("AWS_REGION", "AGENTCORE_RUNTIME_ARN")
MISSING = [name for name in REQUIRED if not os.environ.get(name)]

pytestmark = [
    pytest.mark.runtime,
    pytest.mark.skipif(bool(MISSING), reason=f"deployed runtime settings missing: {MISSING}"),
]


def test_deployed_ambient_runs_a_queued_job() -> None:
    import boto3

    client = boto3.client("bedrock-agentcore", region_name=os.environ["AWS_REGION"])

    def add_actor(request: Any, **_: Any) -> None:
        request.headers[ACTOR_HEADER] = "ambient-worker"

    client.meta.events.register_first("before-sign.bedrock-agentcore.InvokeAgentRuntime", add_actor)
    response = client.invoke_agent_runtime(
        agentRuntimeArn=os.environ["AGENTCORE_RUNTIME_ARN"],
        qualifier=os.environ.get("AGENTCORE_ENDPOINT", "DEV"),
        runtimeSessionId=f"e2e-{uuid.uuid4()}",
        payload=json.dumps({"prompt": "index the new invoice pack"}).encode("utf-8"),
    )
    body = json.loads(response["response"].read())
    assert body["status"] == "completed"
    assert body["release_id"] != "unreleased"

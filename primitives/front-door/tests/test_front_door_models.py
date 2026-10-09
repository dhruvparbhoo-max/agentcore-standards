from __future__ import annotations

from typing import Any

import pytest
from agentcore_front_door import ModelAccess, ModelRoute, ModelRouteError, ModelUnavailable
from agentcore_front_door.models import PROFILE_ENV, WallClock, retry_after_ms
from agentcore_recovery import Clock, RecoveryBudget
from botocore.exceptions import ClientError

MODEL = {"primary": "eu.model-a", "fallback": "eu.model-b", "region_profile": "eu", "team_tag": "platform"}
OK = {"output": {"message": {"content": [{"text": "hi"}]}}, "usage": {"inputTokens": 10, "outputTokens": 5}}


def _error(code: str, retry_after: str | None = None) -> ClientError:
    response: dict[str, Any] = {"Error": {"Code": code, "Message": code}}
    if retry_after is not None:
        response["ResponseMetadata"] = {"HTTPHeaders": {"retry-after": retry_after}}
    return ClientError(response, "Converse")  # type: ignore[arg-type]


class Bedrock:
    def __init__(self, plan: dict[str, list[Any]]) -> None:
        self.plan = plan
        self.calls: list[str] = []

    def converse(self, **kwargs: Any) -> Any:
        model = kwargs["modelId"]
        self.calls.append(model)
        step = self.plan[model].pop(0) if self.plan[model] else OK
        if isinstance(step, Exception):
            raise step
        return step


def _access(plan: dict[str, list[Any]]) -> tuple[ModelAccess, Bedrock]:
    client = Bedrock(plan)
    budget = RecoveryBudget(max_attempts=3, max_elapsed_ms=10_000, base_delay_ms=10, max_delay_ms=100)
    route = ModelRoute.from_pattern(MODEL, region="eu-west-2", env={})
    return ModelAccess(route=route, client=client, budget=budget, clock=Clock()), client


def test_route_requires_the_eu_geography() -> None:
    with pytest.raises(ModelRouteError, match="geographic"):
        ModelRoute.from_pattern({**MODEL, "primary": "us.model-a"}, region="eu-west-2", env={})
    with pytest.raises(ModelRouteError, match="differ"):
        ModelRoute.from_pattern({**MODEL, "fallback": "eu.model-a"}, region="eu-west-2", env={})


def test_per_agent_profile_from_the_environment_wins() -> None:
    profile = "arn:" + "aws:bedrock:eu-west-2:000000000000:application-inference-profile/abc"
    route = ModelRoute.from_pattern(MODEL, region="eu-west-2", env={PROFILE_ENV: profile})
    assert route.primary == profile and route.fallback == "eu.model-b"


def test_throttles_are_retried_then_succeed() -> None:
    access, client = _access({"eu.model-a": [_error("ThrottlingException"), _error("ServiceUnavailableException")]})
    assert access.converse(messages=[]) == OK
    assert client.calls == ["eu.model-a"] * 3
    assert access.usage.as_dict() == {"model_calls": 1, "input_tokens": 10, "output_tokens": 5, "model": "eu.model-a"}


def test_spent_retries_fall_back_to_the_second_profile() -> None:
    access, client = _access({"eu.model-a": [_error("ThrottlingException")] * 3, "eu.model-b": []})
    access.converse(messages=[])
    assert client.calls == ["eu.model-a"] * 3 + ["eu.model-b"]
    assert access.usage.model == "eu.model-b"


def test_fatal_errors_do_not_retry_or_fall_back() -> None:
    access, client = _access({"eu.model-a": [_error("ValidationException")], "eu.model-b": []})
    with pytest.raises(ClientError):
        access.converse(messages=[])
    assert client.calls == ["eu.model-a"]


def test_both_profiles_down_raises_model_unavailable() -> None:
    access, _client = _access(
        {"eu.model-a": [_error("ThrottlingException")] * 3, "eu.model-b": [_error("ThrottlingException")] * 3}
    )
    with pytest.raises(ModelUnavailable) as caught:
        access.converse(messages=[])
    assert caught.value.attempts == 6 and caught.value.code == "ThrottlingException"


def test_retry_after_is_read_and_stretches_the_sleep_up_to_the_cap() -> None:
    assert retry_after_ms(_error("ThrottlingException", "2")) == 2000
    assert retry_after_ms(_error("ThrottlingException")) == 0
    slept: list[float] = []
    clock = WallClock(cap_ms=1500, sleep=slept.append)
    clock.hint_ms = 2000
    clock.sleep(10)
    clock.sleep(10)
    assert slept == [1.5, 0.01]

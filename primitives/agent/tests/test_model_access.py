from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from agentcore_agent import build_agent, echo_script
from agentcore_agent.config import PatternConfig, load_pattern
from agentcore_agent.models import langchain_model, route_for, strands_model
from agentcore_front_door import ModelRoute
from botocore.exceptions import ClientError
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage

TEMPLATE = Path(__file__).resolve().parents[3] / "patterns" / "_template"
ROUTE = ModelRoute(primary="eu.a", fallback="eu.b", region="eu-west-2", region_profile="eu", team_tag="t")


@pytest.fixture
def template_config() -> PatternConfig:
    return load_pattern(TEMPLATE)


def _throttle() -> ClientError:
    return ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow"}}, "Converse")


class Failing(GenericFakeChatModel):
    error: Any = None

    def _generate(self, *args: Any, **kwargs: Any) -> Any:
        raise self.error

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self


class Fake(GenericFakeChatModel):
    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self


def _models(primary_error: Exception | None) -> dict[str, Any]:
    good = Fake(messages=iter([AIMessage(content="from-b")]))
    if primary_error is None:
        return {"eu.a": Fake(messages=iter([AIMessage(content="from-a")])), "eu.b": good}
    primary = Failing(messages=iter([]), error=primary_error)
    return {"eu.a": primary, "eu.b": good}


def test_route_reads_the_pattern(template_config: PatternConfig) -> None:
    route = route_for(template_config, env={})
    assert route.primary.startswith("eu.") and route.fallback.startswith("eu.")
    assert route.max_retries == int(template_config.section("lifecycle")["max_retries"])


def test_langchain_throttle_falls_back() -> None:
    models = _models(_throttle())
    chat = langchain_model(ROUTE, make=models.__getitem__)
    assert chat.invoke([HumanMessage(content="hi")]).content == "from-b"
    bound = langchain_model(ROUTE, make=_models(_throttle()).__getitem__).bind_tools([])
    assert bound.invoke([HumanMessage(content="hi")]).content == "from-b"


def test_langchain_healthy_primary_answers() -> None:
    chat = langchain_model(ROUTE, make=_models(None).__getitem__)
    assert chat.bind_tools([]).invoke([HumanMessage(content="hi")]).content == "from-a"


def test_langchain_fatal_error_does_not_fall_back() -> None:
    fatal = ClientError({"Error": {"Code": "ValidationException", "Message": "bad"}}, "Converse")
    chat = langchain_model(ROUTE, make=_models(fatal).__getitem__)
    with pytest.raises(ClientError):
        chat.invoke([HumanMessage(content="hi")])


def test_langchain_loop_reports_usage(template_config: PatternConfig) -> None:
    reply = AIMessage(content="done", usage_metadata={"input_tokens": 11, "output_tokens": 7, "total_tokens": 18})
    reply.response_metadata = {"model_name": "eu.a"}
    agent = build_agent(template_config, model=Fake(messages=iter([reply])))
    result = agent.run("hello", session_id="s" * 40, actor_id="alice")
    assert result.usage is not None
    assert result.usage.as_dict() == {"model_calls": 1, "input_tokens": 11, "output_tokens": 7, "model": "eu.a"}


def test_scripted_turn_reports_a_model_call(template_config: PatternConfig) -> None:
    result = build_agent(template_config, script=echo_script()).run("hi", session_id="s" * 40, actor_id="a")
    assert result.usage is not None and result.usage.model_calls == 1


class StrandsFake:
    def __init__(self, name: str, error: Exception | None = None) -> None:
        self.name = name
        self.error = error

    def get_config(self) -> dict[str, Any]:
        return {"model_id": self.name}

    async def stream(self, *args: Any, **kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        if self.error is not None:
            raise self.error
        yield {"from": self.name}


def _drain(model: Any) -> list[Any]:
    async def run() -> list[Any]:
        return [event async for event in model.stream([], None, None)]

    return asyncio.run(run())


def test_strands_throttle_falls_back_before_the_first_event() -> None:
    from strands.types.exceptions import ModelThrottledException

    models = {"eu.a": StrandsFake("eu.a", ModelThrottledException("slow")), "eu.b": StrandsFake("eu.b")}
    assert _drain(strands_model(ROUTE, make=models.__getitem__)) == [{"from": "eu.b"}]


def test_strands_fatal_error_does_not_fall_back() -> None:
    models = {"eu.a": StrandsFake("eu.a", ValueError("bad")), "eu.b": StrandsFake("eu.b")}
    with pytest.raises(ValueError):
        _drain(strands_model(ROUTE, make=models.__getitem__))


def test_no_fallback_returns_the_primary() -> None:
    route = ModelRoute(primary="eu.a", fallback="", region="eu-west-2", region_profile="eu", team_tag="t")
    fake = StrandsFake("eu.a")
    assert strands_model(route, make=lambda _id: fake) is fake

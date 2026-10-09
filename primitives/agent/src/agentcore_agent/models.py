"""LangChain and Strands faces of the front door's model access layer.

``agentcore_front_door.models`` owns the route (primary, fallback, geography,
per-agent profile) and which faults are retryable. Here each framework's
Bedrock client gets botocore ``adaptive`` retries capped at
``lifecycle.max_retries`` (the eval-first sample's client config), and a
retryable failure that survives those retries moves to the fallback profile.
A fatal error (a bad request, a schema rejection) does not fall back.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any

from agentcore_front_door.models import ModelRoute, adaptive_config, retryable
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable, RunnableLambda

from agentcore_agent.config import PatternConfig


class _FallBack(Exception):
    """Internal signal: the primary failed in a way the fallback may answer."""


def route_for(config: PatternConfig, *, env: Mapping[str, str] | None = None) -> ModelRoute:
    source = os.environ if env is None else env
    return ModelRoute.from_pattern(
        config.section("model"),
        region=source.get("AWS_REGION", str(config.section("data")["region"])),
        max_retries=int(config.section("lifecycle")["max_retries"]),
        env=source,
    )


def guarded(primary: Runnable[Any, Any], fallback: Runnable[Any, Any] | None) -> Runnable[Any, Any]:
    """``primary``, then ``fallback`` only when the primary's error is retryable."""
    if fallback is None:
        return primary

    def run(value: Any, config: Any = None) -> Any:
        try:
            return primary.invoke(value, config)
        except Exception as exc:
            if retryable(exc):
                raise _FallBack(str(exc)) from exc
            raise

    return RunnableLambda(run).with_fallbacks([fallback], exceptions_to_handle=(_FallBack,))


class FallbackChatModel(BaseChatModel):
    """A chat model ``create_agent`` accepts. ``bind_tools`` binds both profiles."""

    primary: Any
    fallback: Any = None

    @property
    def _llm_type(self) -> str:
        return "agentcore-fallback"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Runnable[Any, Any]:
        primary = self.primary.bind_tools(tools, **kwargs)
        fallback = self.fallback.bind_tools(tools, **kwargs) if self.fallback is not None else None
        return guarded(primary, fallback)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        del run_manager, kwargs
        primary = self.primary.bind(stop=stop) if stop else self.primary
        fallback = self.fallback.bind(stop=stop) if stop and self.fallback is not None else self.fallback
        message = guarded(primary, fallback).invoke(messages)
        return ChatResult(generations=[ChatGeneration(message=message)])


def langchain_model(route: ModelRoute, *, make: Callable[[str], Any] | None = None) -> FallbackChatModel:
    if make is None:
        from langchain_aws import ChatBedrockConverse

        def make(model_id: str) -> Any:
            return ChatBedrockConverse(
                model=model_id, region_name=route.region, config=adaptive_config(route.max_retries)
            )

    return FallbackChatModel(primary=make(route.primary), fallback=make(route.fallback) if route.fallback else None)


def strands_model(route: ModelRoute, *, make: Callable[[str], Any] | None = None) -> Any:
    if make is None:
        from strands.models import BedrockModel

        def make(model_id: str) -> Any:
            return BedrockModel(
                model_id=model_id, region_name=route.region, boto_client_config=adaptive_config(route.max_retries)
            )

    primary = make(route.primary)
    if not route.fallback:
        return primary
    return _strands_fallback(primary, make(route.fallback))


def _strands_fallback(primary: Any, fallback: Any) -> Any:
    from strands.models.model import Model
    from strands.types.exceptions import ModelThrottledException

    class FallbackStrandsModel(Model):
        """Stream from the primary. A retryable failure before the first event streams from the fallback."""

        def __init__(self) -> None:
            self.primary = primary
            self.fallback = fallback

        def update_config(self, **model_config: Any) -> None:
            self.primary.update_config(**model_config)

        def get_config(self) -> Any:
            return self.primary.get_config()

        def structured_output(self, output_model: Any, prompt: Any, system_prompt: str | None = None, **kwargs: Any):  # type: ignore[no-untyped-def]
            return self.primary.structured_output(output_model, prompt, system_prompt=system_prompt, **kwargs)

        async def stream(
            self, messages: Any, tool_specs: Any = None, system_prompt: str | None = None, **kwargs: Any
        ) -> AsyncIterator[Any]:
            started = False
            try:
                async for event in self.primary.stream(messages, tool_specs, system_prompt, **kwargs):
                    started = True
                    yield event
                return
            except Exception as exc:
                if started or not (isinstance(exc, ModelThrottledException) or retryable(exc)):
                    raise
            async for event in self.fallback.stream(messages, tool_specs, system_prompt, **kwargs):
                yield event

    return FallbackStrandsModel()

from __future__ import annotations

import io
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from agentcore_front_door import AgentPolicy, DoorSettings, FrontDoor, MemoryStore, Price, Quotas, RuntimeInvoker

SECRET = b"k" * 32
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
RUNTIME = "runtime-under-test"


class FakeRuntime:
    """Records each InvokeAgentRuntime call and replies with ``reply``."""

    def __init__(self, reply: Mapping[str, Any] | None = None, *, error: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.stopped: list[dict[str, Any]] = []
        self.reply = dict(reply or {"status": "completed", "result": "ok", "release_id": "rel-1"})
        self.error = error
        self.during: Any = None

    def invoke_agent_runtime(self, **kwargs: Any) -> Mapping[str, Any]:
        self.calls.append(kwargs)
        if self.during is not None:
            self.during()
        if self.error is not None:
            raise self.error
        body = json.dumps(self.reply).encode()
        return {"statusCode": 200, "contentType": "application/json", "response": io.BytesIO(body)}

    def stop_runtime_session(self, **kwargs: Any) -> Mapping[str, Any]:
        self.stopped.append(kwargs)
        return {}


def policy(**overrides: Any) -> AgentPolicy:
    raw: dict[str, Any] = {
        "agent": "policy-qa",
        "team": "platform",
        "acts_as": "user",
        "endpoint": "DEV",
        "release_id": "rel-1",
        "tools": ["search_policies_kb"],
        "max_turns": 3,
        "max_steps": 4,
        "timeout_s": 60,
        "session_id_min": 33,
        "max_usd_per_run": 0.5,
        "monthly_cap_usd": 10,
        "runtime_arn": RUNTIME,
    }
    raw.update(overrides)
    return AgentPolicy.from_mapping(raw)


def settings(**overrides: Any) -> DoorSettings:
    base: dict[str, Any] = {
        "quotas": Quotas(user_daily=5, team_daily=50, agent_daily=100, user_per_minute=4),
        "user_monthly_usd": 2.0,
        "team_monthly_usd": 5.0,
        "prices": {"eu.model-a": Price(3.0, 15.0)},
    }
    base.update(overrides)
    return DoorSettings(**base)


def make_door(
    runtime: FakeRuntime, store: MemoryStore, *, policies: list[AgentPolicy] | None = None, **kwargs: Any
) -> FrontDoor:
    chosen = policies or [policy()]
    return FrontDoor(
        policies={p.agent: p for p in chosen},
        settings=kwargs.pop("door_settings", settings()),
        store=store,
        binding_secret=SECRET,
        invoker=RuntimeInvoker(runtime),
        now=lambda: NOW,
        **kwargs,
    )

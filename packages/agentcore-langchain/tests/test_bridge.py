"""Registry tools stay behind invoke_tool. create_agent receives those callables."""

from collections.abc import Mapping
from typing import Any

from agentcore_context import assemble_context
from agentcore_langchain import bind_turn, create_runtime_agent, registry_callables, turn_from_headers
from agentcore_langchain.bridge import prompt_from_context
from agentcore_tools import Policy, ToolRegistry


def _registry(*, permit: bool) -> ToolRegistry:
    registry = ToolRegistry()

    @registry.tool(
        name="echo",
        schema={
            "additionalProperties": False,
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "type": "object",
        },
        description="Echo a short value.",
        idempotent=True,
        side_effecting=False,
    )
    def echo(args: Mapping[str, Any]) -> Mapping[str, Any]:
        return {"value": str(args["value"])}

    registry.add_lambda_target("notes", tools=("echo",))
    policy = Policy()
    if permit:
        policy.permit("0.1.0", "echo")
    registry.bind_gateway("gateway-dev", policy=policy)
    return registry


def test_unpermitted_tool_returns_a_fatal_code_without_running_twice() -> None:
    calls = {"n": 0}
    registry = ToolRegistry()

    @registry.tool(
        name="echo",
        schema={
            "additionalProperties": False,
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "type": "object",
        },
        description="Echo a short value.",
        idempotent=True,
        side_effecting=False,
    )
    def echo(args: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["n"] += 1
        return {"value": str(args["value"])}

    registry.add_lambda_target("notes", tools=("echo",))
    registry.bind_gateway("gateway-dev", policy=Policy())
    tool = registry_callables(registry)[0]
    binding = turn_from_headers({"x-agentcore-actor-id": "actor-1"}, agent_version="0.1.0", context_session_id="s" * 33)
    with bind_turn(binding):
        text = tool('{"value":"ping"}')
    assert text.startswith("fatal ")
    assert calls["n"] == 0


def test_permitted_tool_returns_compacted_output() -> None:
    registry = _registry(permit=True)
    tool = registry_callables(registry)[0]
    assert tool.__name__ == "echo"
    binding = turn_from_headers(
        {"X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id": "actor-9"},
        agent_version="0.1.0",
        context_session_id="session-1",
    )
    with bind_turn(binding):
        text = tool('{"value":"ping"}')
    assert "ping" in text


def test_create_runtime_agent_receives_registry_tools(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    def fake_create_agent(*, model: object, tools: list[object], system_prompt: str) -> dict[str, object]:
        captured["model"] = model
        captured["tools"] = tools
        captured["system_prompt"] = system_prompt
        return {"wired": True}

    import langchain.agents as agents

    monkeypatch.setattr(agents, "create_agent", fake_create_agent)
    assembled = assemble_context(system="Cite passages.", user="Where is the refund rule?", budget_tokens=200)
    agent = create_runtime_agent(
        model="scripted",
        registry=_registry(permit=True),
        system_prompt=prompt_from_context(assembled),
    )
    assert agent == {"wired": True}
    tools = captured["tools"]
    assert isinstance(tools, list)
    assert tools[0].__name__ == "echo"  # type: ignore[attr-defined]
    assert "Cite passages." in str(captured["system_prompt"])

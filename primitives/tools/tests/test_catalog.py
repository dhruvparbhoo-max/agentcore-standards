"""Compaction, citations, and index-then-load. Loading a tool does not permit it."""

from collections.abc import Mapping
from typing import Any

from agentcore_tools import (
    Citation,
    Corpus,
    Passage,
    Policy,
    ToolCatalog,
    ToolRegistry,
    compact_tool_output,
)
from support import AGENT_VERSION


def test_compact_keeps_head_and_tail() -> None:
    text = "HEAD-" + ("m" * 500) + "-TAIL"
    compacted = compact_tool_output(text, tool_name="echo", max_chars=120)
    assert compacted.truncated
    assert compacted.text.startswith("HEAD-")
    assert compacted.text.endswith("-TAIL")
    assert "omitted=" in compacted.text
    assert compacted.kept_chars <= 120


def test_retrieve_cites_a_match_and_refuses_an_unrelated_query() -> None:
    corpus = Corpus()
    corpus.add(
        Passage(
            passage_id="refunds",
            title="Refund rule",
            text="Refunds are issued to the original payment method within ten days.",
        )
    )
    hits = corpus.retrieve("How do refunds work?")
    assert len(hits) == 1
    assert isinstance(hits[0], Citation)
    assert hits[0].passage_id == "refunds"
    assert hits[0].method == "lexical"
    assert "refunds" in hits[0].render()
    assert corpus.retrieve("weather forecast") == ()


def test_catalog_index_omits_the_schema_until_load() -> None:
    calls = {"n": 0}

    def handler(args: Mapping[str, Any]) -> Mapping[str, Any]:
        calls["n"] += 1
        return {"value": str(args["value"])}

    registry = ToolRegistry()

    @registry.tool(
        name="echo",
        schema={
            "additionalProperties": False,
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "type": "object",
        },
        description="Echo a short value back to the caller.",
        idempotent=True,
        side_effecting=False,
    )
    def echo(args: Mapping[str, Any]) -> Mapping[str, Any]:
        return handler(args)

    registry.add_lambda_target("notes", tools=("echo",))
    registry.bind_gateway("gateway-dev", policy=Policy())
    catalog = ToolCatalog(registry)
    cards = catalog.index()
    assert len(cards) == 1
    assert cards[0].name == "echo"
    assert not hasattr(cards[0], "inputSchema")
    loaded = catalog.load("echo")
    assert "inputSchema" in loaded
    disclosed = catalog.disclose("echo value")
    assert [card.name for card in disclosed] == ["echo"]
    denied = registry.invoke_tool("echo", {"value": "x"}, agent_version=AGENT_VERSION)
    assert denied.error is not None
    assert denied.error.code == "policy_denied"
    assert calls["n"] == 0

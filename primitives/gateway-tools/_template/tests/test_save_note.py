from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from agentcore_agent.registry import load_tool, registry_record, tool_problems
from agentcore_tools.idempotency import args_hash as shared_args_hash
from template_tool.handler import args_hash, save_note

FOLDER = Path(__file__).resolve().parents[1]


class MemoryStore:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.writes = 0

    def put_if_absent(self, key: str, item: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if key in self.items:
            return self.items[key]
        self.items[key] = dict(item)
        self.writes += 1
        return None


EVENT = {"idempotency_key": "note-key-0001", "actor_id": "user-1", "text": "call the supplier"}


def test_double_invoke_has_one_effect() -> None:
    store = MemoryStore()
    first = save_note(EVENT, store)
    second = save_note(EVENT, store)
    assert first == {"status": "created", "note_id": "note-key-0001"}
    assert second == {"status": "replayed", "note_id": "note-key-0001"}
    assert store.writes == 1


def test_same_key_different_arguments_is_a_conflict() -> None:
    store = MemoryStore()
    save_note(EVENT, store)
    clash = save_note({**EVENT, "text": "something else"}, store)
    assert clash["error"] == "idempotency_conflict"
    assert store.items["note-key-0001"]["text"] == "call the supplier"


def test_missing_field_stores_nothing() -> None:
    store = MemoryStore()
    assert save_note({"idempotency_key": "k" * 8}, store)["error"] == "schema"
    assert store.writes == 0


def test_hash_matches_the_shared_helper() -> None:
    args = {"actor_id": "user-1", "text": "x"}
    assert args_hash(args) == shared_args_hash(args)


def test_tool_yaml_is_valid_and_lists_in_registry() -> None:
    raw = yaml.safe_load((FOLDER / "tool.yaml").read_text(encoding="utf-8"))
    assert tool_problems(raw, folder_name=FOLDER.name) == []
    record = registry_record(load_tool(FOLDER), registry_id="registry-test", gateway_url="https://gateway.invalid/mcp")
    assert record["descriptorType"] == "MCP"
    assert record["name"] == "save_note"
    assert '"destructiveHint": true' in record["descriptors"]["mcp"]["tools"]["inlineContent"]


def test_side_effect_tool_must_require_a_key() -> None:
    raw = yaml.safe_load((FOLDER / "tool.yaml").read_text(encoding="utf-8"))
    raw["idempotency"] = "not-needed"
    assert any("idempotency" in problem for problem in tool_problems(raw))

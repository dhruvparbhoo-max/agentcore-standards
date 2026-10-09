from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from agentcore_agent.registry import load_tool, registry_record, tool_problems
from submit_change.handler import MemoryChangeStore, args_hash, submit_change

FOLDER = Path(__file__).resolve().parents[1]
EVENT = {"idempotency_key": "change-key-0001", "actor_id": "user-1", "summary": "rename the folder"}


class CountingStore(MemoryChangeStore):
    def __init__(self) -> None:
        super().__init__()
        self.writes = 0

    def put_if_absent(self, key: str, item: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if key in self.items:
            return self.items[key]
        self.writes += 1
        return super().put_if_absent(key, item)


def test_double_invoke_has_one_effect() -> None:
    store = CountingStore()
    first = submit_change(EVENT, store)
    second = submit_change(EVENT, store)
    assert first == {"status": "created", "change_id": "change-key-0001"}
    assert second == {"status": "replayed", "change_id": "change-key-0001"}
    assert store.writes == 1


def test_same_key_different_arguments_is_a_conflict() -> None:
    store = CountingStore()
    submit_change(EVENT, store)
    other = {**EVENT, "summary": "a different change"}
    assert submit_change(other, store)["error"] == "idempotency_conflict"
    assert store.writes == 1


def test_fingerprint_matches_the_shared_helper() -> None:
    from agentcore_tools.idempotency import args_hash as shared

    body = {"actor_id": EVENT["actor_id"], "summary": EVENT["summary"]}
    assert args_hash(body) == shared(body)


def test_tool_yaml_is_a_valid_registry_listing() -> None:
    listing = load_tool(FOLDER)
    assert listing.name == "submit_change" and listing.action == "change"
    assert tool_problems(yaml.safe_load((FOLDER / "tool.yaml").read_text(encoding="utf-8"))) == []
    record = registry_record(listing, registry_id="reg", gateway_url="https://gateway.example")
    assert record["name"] == "submit_change"

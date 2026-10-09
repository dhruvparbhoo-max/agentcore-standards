"""Gateway Lambda target for ``submit_change``.

A retried invoke may not carry the caller's idempotency claim, so the handler
keeps its own natural key: a conditional put on ``idempotency_key``.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from typing import Any, Protocol

TABLE_ENV = "CHANGES_TABLE"
_REQUIRED = ("idempotency_key", "actor_id", "summary")


class ChangeStore(Protocol):
    def put_if_absent(self, key: str, item: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """Store ``item`` unless ``key`` exists. Return the existing item, or ``None`` when stored."""


class MemoryChangeStore:
    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}

    def put_if_absent(self, key: str, item: Mapping[str, Any]) -> Mapping[str, Any] | None:
        if key in self.items:
            return self.items[key]
        self.items[key] = dict(item)
        return None


class DynamoChangeStore:
    def __init__(self, table: Any) -> None:
        self._table = table

    def put_if_absent(self, key: str, item: Mapping[str, Any]) -> Mapping[str, Any] | None:
        try:
            self._table.put_item(Item={"pk": key, **item}, ConditionExpression="attribute_not_exists(pk)")
        except self._table.meta.client.exceptions.ConditionalCheckFailedException:
            found = self._table.get_item(Key={"pk": key}, ConsistentRead=True).get("Item")
            return found if isinstance(found, Mapping) else {}
        return None


def args_hash(args: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(args), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def submit_change(event: Mapping[str, Any], store: ChangeStore) -> dict[str, Any]:
    missing = [field for field in _REQUIRED if not isinstance(event.get(field), str) or not event[field]]
    if missing:
        return {"error": "schema", "missing": missing}
    key = str(event["idempotency_key"])
    fingerprint = args_hash({field: event[field] for field in _REQUIRED if field != "idempotency_key"})
    existing = store.put_if_absent(
        key, {"args_hash": fingerprint, "actor_id": event["actor_id"], "summary": event["summary"]}
    )
    if existing is None:
        return {"status": "created", "change_id": key}
    if existing.get("args_hash") != fingerprint:
        return {"error": "idempotency_conflict", "change_id": key}
    return {"status": "replayed", "change_id": key}


_store: ChangeStore | None = None


def _default_store() -> ChangeStore:
    global _store
    if _store is None:
        endpoint = os.environ.get("DYNAMODB_ENDPOINT")
        if not endpoint and not os.environ.get(TABLE_ENV):
            _store = MemoryChangeStore()
        else:
            import boto3

            table = boto3.resource("dynamodb", endpoint_url=endpoint or None).Table(os.environ[TABLE_ENV])
            _store = DynamoChangeStore(table)
    return _store


def handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    return submit_change(event, _default_store())

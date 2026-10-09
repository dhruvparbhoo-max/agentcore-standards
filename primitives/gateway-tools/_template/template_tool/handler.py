"""Gateway Lambda target for ``save_note``.

Gateway passes the tool arguments as the event. A retried invoke may not carry
the caller's idempotency claim, so the handler keeps its own natural key: a
conditional put on ``idempotency_key``. The same key with the same arguments
replays the first result. The same key with different arguments is a conflict
and stores nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from typing import Any, Protocol

TABLE_ENV = "NOTES_TABLE"
_REQUIRED = ("idempotency_key", "actor_id", "text")


class NoteStore(Protocol):
    def put_if_absent(self, key: str, item: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """Store ``item`` unless ``key`` exists. Return the existing item, or ``None`` when stored."""


class DynamoNoteStore:
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
    """Same canonical form as ``agentcore_tools.idempotency.args_hash``."""
    canonical = json.dumps(dict(args), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def save_note(event: Mapping[str, Any], store: NoteStore) -> dict[str, Any]:
    missing = [field for field in _REQUIRED if not isinstance(event.get(field), str) or not event[field]]
    if missing:
        return {"error": "schema", "missing": missing}
    key = str(event["idempotency_key"])
    fingerprint = args_hash({field: event[field] for field in _REQUIRED if field != "idempotency_key"})
    existing = store.put_if_absent(
        key,
        {"args_hash": fingerprint, "actor_id": event["actor_id"], "text": event["text"]},
    )
    if existing is None:
        return {"status": "created", "note_id": key}
    if existing.get("args_hash") != fingerprint:
        return {"error": "idempotency_conflict", "note_id": key}
    return {"status": "replayed", "note_id": key}


_store: NoteStore | None = None


def _default_store() -> NoteStore:
    global _store
    if _store is None:
        import boto3

        endpoint = os.environ.get("DYNAMODB_ENDPOINT") or None
        table = boto3.resource("dynamodb", endpoint_url=endpoint).Table(os.environ[TABLE_ENV])
        _store = DynamoNoteStore(table)
    return _store


def handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    del context
    return save_note(event, _default_store())

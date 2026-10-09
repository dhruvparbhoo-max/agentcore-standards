"""Where the front door keeps counters, session leases, kill switches, and the audit trail.

Two tables. The state table holds counters, leases, and switches, with a TTL on
counters and leases. The audit table is append-only: every put is conditional on
the key not existing, and the front door's role gets ``PutItem`` on it and
nothing else (``infra/constructs`` FrontDoor). Atomic ``ADD`` counters are
copied from aws-samples/sample-agent-platform-with-agentcore
``backend/app/services/governance_service.py``; the audit row shape from the
same sample's ``audit_service.py`` (both MIT-0).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

AGENT = "agent"
TOOL = "tool"
SOURCE = "source"
SWITCH_SCOPES = (AGENT, TOOL, SOURCE)


class AuditWriteFailed(Exception):
    """The audit row was not written. The call it describes does not start."""


@dataclass(frozen=True)
class Switch:
    scope: str
    name: str
    enabled: bool
    reason: str = ""
    set_by: str = ""
    set_at: str = ""


class Store(Protocol):
    def increment(self, key: str, *, by: float = 1, ttl_epoch_s: int = 0, limit: float | None = None) -> float | None:
        """Add ``by`` and return the new total. With ``limit``, add only while the total is below it, else None."""

    def read(self, key: str) -> float:
        """The current total for ``key``, or zero."""

    def acquire_lease(self, session_id: str, *, holder: str, now_s: int, expires_s: int) -> bool:
        """Take the session for one call. False while another holder's lease is unexpired."""

    def release_lease(self, session_id: str, *, holder: str) -> None:
        """Give the session back. Only the holder can release it."""

    def switch(self, scope: str, name: str) -> Switch | None:
        """The kill switch for one agent, tool, or source. None means never set (on)."""

    def put_switch(self, switch: Switch) -> None:
        """Set a kill switch."""

    def switches(self) -> list[Switch]:
        """Every switch that has been set."""

    def append_audit(self, entry: Mapping[str, Any]) -> None:
        """Write one immutable audit row. Raises ``AuditWriteFailed`` when it cannot."""


class MemoryStore:
    """In-process store for tests and ``make local``."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: dict[str, float] = {}
        self.leases: dict[str, tuple[str, int]] = {}
        self._switches: dict[tuple[str, str], Switch] = {}
        self.audit: list[dict[str, Any]] = []
        self._audit_keys: set[tuple[str, str]] = set()
        self.fail_audit = False

    def increment(self, key: str, *, by: float = 1, ttl_epoch_s: int = 0, limit: float | None = None) -> float | None:
        del ttl_epoch_s
        with self._lock:
            current = self.counters.get(key, 0.0)
            if limit is not None and current >= limit:
                return None
            self.counters[key] = current + by
            return self.counters[key]

    def read(self, key: str) -> float:
        with self._lock:
            return self.counters.get(key, 0.0)

    def acquire_lease(self, session_id: str, *, holder: str, now_s: int, expires_s: int) -> bool:
        with self._lock:
            current = self.leases.get(session_id)
            if current is not None and current[0] != holder and current[1] > now_s:
                return False
            self.leases[session_id] = (holder, expires_s)
            return True

    def release_lease(self, session_id: str, *, holder: str) -> None:
        with self._lock:
            current = self.leases.get(session_id)
            if current is not None and current[0] == holder:
                del self.leases[session_id]

    def switch(self, scope: str, name: str) -> Switch | None:
        return self._switches.get((scope, name))

    def put_switch(self, switch: Switch) -> None:
        _check_scope(switch.scope)
        self._switches[(switch.scope, switch.name)] = switch

    def switches(self) -> list[Switch]:
        return sorted(self._switches.values(), key=lambda s: (s.scope, s.name))

    def append_audit(self, entry: Mapping[str, Any]) -> None:
        key = (str(entry["pk"]), str(entry["sk"]))
        with self._lock:
            if self.fail_audit or key in self._audit_keys:
                raise AuditWriteFailed("audit row not written")
            self._audit_keys.add(key)
            self.audit.append(dict(entry))


class DynamoStore:
    """DynamoDB tables made by the FrontDoor construct. ``state`` has ``pk``/``sk`` and ``expires_at`` TTL."""

    def __init__(self, *, state_table: Any, audit_table: Any) -> None:
        self._state = state_table
        self._audit = audit_table

    @classmethod
    def from_names(cls, state: str, audit: str, *, endpoint_url: str | None = None) -> DynamoStore:
        import boto3

        resource = boto3.resource("dynamodb", endpoint_url=endpoint_url) if endpoint_url else boto3.resource("dynamodb")
        return cls(state_table=resource.Table(state), audit_table=resource.Table(audit))

    def increment(self, key: str, *, by: float = 1, ttl_epoch_s: int = 0, limit: float | None = None) -> float | None:
        from botocore.exceptions import ClientError

        names = {"#c": "count"}
        values: dict[str, Any] = {":by": Decimal(str(by))}
        update = "ADD #c :by"
        if ttl_epoch_s:
            update += " SET #e = if_not_exists(#e, :ttl)"
            names["#e"] = "expires_at"
            values[":ttl"] = ttl_epoch_s
        kwargs: dict[str, Any] = {
            "Key": {"pk": key, "sk": "count"},
            "UpdateExpression": update,
            "ExpressionAttributeNames": names,
            "ExpressionAttributeValues": values,
            "ReturnValues": "UPDATED_NEW",
        }
        if limit is not None:
            kwargs["ConditionExpression"] = "attribute_not_exists(#c) OR #c < :limit"
            values[":limit"] = Decimal(str(limit))
        try:
            response = self._state.update_item(**kwargs)
        except ClientError as exc:
            if _code(exc) == "ConditionalCheckFailedException":
                return None
            raise
        return float(response["Attributes"]["count"])

    def read(self, key: str) -> float:
        item = self._state.get_item(Key={"pk": key, "sk": "count"}, ConsistentRead=True).get("Item") or {}
        return float(item.get("count", 0))

    def acquire_lease(self, session_id: str, *, holder: str, now_s: int, expires_s: int) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._state.put_item(
                Item={"pk": f"lease#{session_id}", "sk": "lease", "holder": holder, "expires_at": expires_s},
                ConditionExpression="attribute_not_exists(pk) OR expires_at <= :now OR holder = :holder",
                ExpressionAttributeValues={":now": now_s, ":holder": holder},
            )
        except ClientError as exc:
            if _code(exc) == "ConditionalCheckFailedException":
                return False
            raise
        return True

    def release_lease(self, session_id: str, *, holder: str) -> None:
        from botocore.exceptions import ClientError

        try:
            self._state.delete_item(
                Key={"pk": f"lease#{session_id}", "sk": "lease"},
                ConditionExpression="holder = :holder",
                ExpressionAttributeValues={":holder": holder},
            )
        except ClientError as exc:
            if _code(exc) != "ConditionalCheckFailedException":
                raise

    def switch(self, scope: str, name: str) -> Switch | None:
        _check_scope(scope)
        item = self._state.get_item(Key={"pk": "switch", "sk": f"{scope}#{name}"}, ConsistentRead=True).get("Item")
        return _switch(item) if item else None

    def put_switch(self, switch: Switch) -> None:
        _check_scope(switch.scope)
        self._state.put_item(
            Item={
                "pk": "switch",
                "sk": f"{switch.scope}#{switch.name}",
                "scope": switch.scope,
                "name": switch.name,
                "enabled": switch.enabled,
                "reason": switch.reason,
                "set_by": switch.set_by,
                "set_at": switch.set_at,
            }
        )

    def switches(self) -> list[Switch]:
        items = self._state.query(KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": "switch"}).get(
            "Items", []
        )
        return [_switch(item) for item in items]

    def append_audit(self, entry: Mapping[str, Any]) -> None:
        try:
            self._audit.put_item(Item=_to_dynamo(entry), ConditionExpression="attribute_not_exists(pk)")
        except Exception as exc:
            raise AuditWriteFailed(f"audit row not written: {type(exc).__name__}") from exc


def _switch(item: Mapping[str, Any]) -> Switch:
    return Switch(
        scope=str(item["scope"]),
        name=str(item["name"]),
        enabled=bool(item["enabled"]),
        reason=str(item.get("reason", "")),
        set_by=str(item.get("set_by", "")),
        set_at=str(item.get("set_at", "")),
    )


def _check_scope(scope: str) -> None:
    if scope not in SWITCH_SCOPES:
        raise ValueError(f"switch scope must be one of {SWITCH_SCOPES}")


def _code(exc: Any) -> str:
    return str(getattr(exc, "response", {}).get("Error", {}).get("Code", ""))


def _to_dynamo(value: Any) -> Any:
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, Mapping):
        return {str(k): _to_dynamo(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_dynamo(v) for v in value]
    return str(value)

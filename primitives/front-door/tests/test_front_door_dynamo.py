"""DynamoStore against DynamoDB Local. Skipped unless ``DYNAMODB_ENDPOINT`` is set (``make local`` sets it)."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from agentcore_front_door import DynamoStore, Switch
from agentcore_front_door.store import AuditWriteFailed

ENDPOINT = os.environ.get("DYNAMODB_ENDPOINT", "")
pytestmark = pytest.mark.skipif(not ENDPOINT, reason="DYNAMODB_ENDPOINT is not set; start dynamodb-local")


@pytest.fixture
def store() -> Iterator[DynamoStore]:
    import boto3

    os.environ.setdefault("AWS_DEFAULT_REGION", "eu-west-2")
    os.environ.setdefault("AWS_ACCESS_KEY_ID", "local")
    os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "local")
    client = boto3.client("dynamodb", endpoint_url=ENDPOINT)
    names = [f"fd-{kind}-{uuid.uuid4().hex[:8]}" for kind in ("state", "audit")]
    for name in names:
        client.create_table(
            TableName=name,
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
                {"AttributeName": "sk", "AttributeType": "S"},
            ],
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            BillingMode="PAY_PER_REQUEST",
        )
    yield DynamoStore.from_names(names[0], names[1], endpoint_url=ENDPOINT)
    for name in names:
        client.delete_table(TableName=name)


def test_counters_add_atomically_and_respect_a_limit(store: DynamoStore) -> None:
    assert store.increment("quota#user#a#d", ttl_epoch_s=100) == 1
    assert store.increment("quota#user#a#d", ttl_epoch_s=100) == 2
    assert store.increment("spend#x", by=0.25) == pytest.approx(0.25)
    assert store.read("spend#x") == pytest.approx(0.25)
    assert store.increment("turns#s", limit=1) == 1
    assert store.increment("turns#s", limit=1) is None


def test_leases_block_a_second_holder_until_released_or_expired(store: DynamoStore) -> None:
    assert store.acquire_lease("s1", holder="a", now_s=100, expires_s=200)
    assert not store.acquire_lease("s1", holder="b", now_s=150, expires_s=250)
    assert store.acquire_lease("s1", holder="b", now_s=201, expires_s=300)
    store.release_lease("s1", holder="a")
    assert not store.acquire_lease("s1", holder="c", now_s=250, expires_s=350)
    store.release_lease("s1", holder="b")
    assert store.acquire_lease("s1", holder="c", now_s=250, expires_s=350)


def test_switches_round_trip(store: DynamoStore) -> None:
    store.put_switch(Switch(scope="agent", name="policy-qa", enabled=False, reason="drill", set_by="alice"))
    found = store.switch("agent", "policy-qa")
    assert found is not None and not found.enabled and found.reason == "drill"
    assert [s.name for s in store.switches()] == ["policy-qa"]
    assert store.switch("tool", "other") is None


def test_audit_rows_cannot_be_overwritten(store: DynamoStore) -> None:
    row = {"pk": "audit#d", "sk": "t#1#accepted", "usd": 0.1, "breaches": ["steps"]}
    store.append_audit(row)
    with pytest.raises(AuditWriteFailed):
        store.append_audit({**row, "usd": 0.0})

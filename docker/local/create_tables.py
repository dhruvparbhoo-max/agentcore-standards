"""Create the local DynamoDB tables listed in ``tables.json``.

Runs once inside compose (service ``tables``) against DynamoDB Local. The
deployed tables come from CDK; this file only mirrors their key schema.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import boto3

TABLES = Path(__file__).with_name("tables.json")


def main() -> int:
    client = boto3.client("dynamodb", endpoint_url=os.environ["DYNAMODB_ENDPOINT"])
    for _ in range(30):
        try:
            existing = set(client.list_tables()["TableNames"])
            break
        except Exception:
            time.sleep(1)
    else:
        print("DynamoDB Local did not answer", file=sys.stderr)
        return 1
    for table in json.loads(TABLES.read_text(encoding="utf-8")):
        name = table["name"]
        if name in existing:
            print(f"exists {name}")
            continue
        keys = [(table["pk"], "HASH")] + ([(table["sk"], "RANGE")] if table.get("sk") else [])
        client.create_table(
            TableName=name,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": key, "AttributeType": "S"} for key, _ in keys],
            KeySchema=[{"AttributeName": key, "KeyType": kind} for key, kind in keys],
        )
        print(f"created {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

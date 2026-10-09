"""Operator commands. The runbook is docs/runbooks/kill-switch.md.

    agentcore-front-door switch off agent policy-qa --reason "bad answers" --by alice
    agentcore-front-door switch on tool send_email --by alice
    agentcore-front-door switches
    agentcore-front-door stop-session --runtime-arn "$RUNTIME_ARN" --endpoint PROD --session s-...

Table names come from ``FRONT_DOOR_STATE_TABLE`` and ``FRONT_DOOR_AUDIT_TABLE``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from datetime import UTC, datetime

from agentcore_front_door.runtime import RuntimeInvoker
from agentcore_front_door.store import SWITCH_SCOPES, Store, Switch
from agentcore_front_door.wiring import store_from_env


def main(argv: Sequence[str] | None = None, *, store: Store | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentcore-front-door")
    sub = parser.add_subparsers(dest="command", required=True)
    switch = sub.add_parser("switch", help="turn an agent, tool, or source on or off")
    switch.add_argument("state", choices=("on", "off"))
    switch.add_argument("scope", choices=SWITCH_SCOPES)
    switch.add_argument("name")
    switch.add_argument("--reason", default="")
    switch.add_argument("--by", required=True, help="who is pulling the switch")
    sub.add_parser("switches", help="list every switch that has been set")
    stop = sub.add_parser("stop-session", help="StopRuntimeSession for one session")
    stop.add_argument("--runtime-arn", required=True)
    stop.add_argument("--endpoint", required=True)
    stop.add_argument("--session", required=True)
    args = parser.parse_args(argv)

    if args.command == "stop-session":
        import boto3

        stopped = RuntimeInvoker(boto3.client("bedrock-agentcore")).stop(
            runtime_arn=args.runtime_arn, qualifier=args.endpoint, session_id=args.session
        )
        print("stopped" if stopped else "already stopped")
        return 0

    target = store if store is not None else store_from_env(os.environ)
    if args.command == "switches":
        rows = [s.__dict__ for s in target.switches()]
        print(json.dumps(rows, indent=2))
        return 0
    if args.state == "off" and not args.reason:
        print("--reason is required when switching off", file=sys.stderr)
        return 2
    target.put_switch(
        Switch(
            scope=args.scope,
            name=args.name,
            enabled=args.state == "on",
            reason=args.reason,
            set_by=args.by,
            set_at=datetime.now(UTC).isoformat(),
        )
    )
    print(f"{args.scope} {args.name} is {args.state}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

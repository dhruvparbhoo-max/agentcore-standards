"""Author check for double-invoke. This is not an independent Runtime verdict."""

import json
from pathlib import Path
from typing import Any

from agentcore_tools.demo import DEMO_AGENT_VERSION, PUT_RECORD, build_demo_registry
from agentcore_tools.errors import ToolConfigurationError
from agentcore_tools.policy import Policy

EVAL_NAME = "tools.double-invoke"
_GATEWAY_ID = "gateway-local"
_ARN_MARKER = "arn:" + "aws:"


def write_double_invoke_evidence(directory: Path, *, body: str = "stored-body") -> Path:
    """Invoke ``put_record`` twice with one idempotency key and write a JSON file.

    The file records execution and store counts. It does not record the record
    body. A passing file means the handler ran once and the store has one row.
    """
    demo = build_demo_registry()
    policy = Policy()
    policy.permit(DEMO_AGENT_VERSION, PUT_RECORD)
    demo.registry.bind_gateway(_GATEWAY_ID, policy=policy)
    args = {"body": body, "record_id": "rec-1"}
    first = demo.registry.invoke_tool(
        PUT_RECORD,
        args,
        agent_version=DEMO_AGENT_VERSION,
        idempotency_key="invoke-1",
        actor_id="actor-demo",
        runtime_session_id="session-demo",
        request_id="request-demo",
    )
    second = demo.registry.invoke_tool(
        PUT_RECORD,
        args,
        agent_version=DEMO_AGENT_VERSION,
        idempotency_key="invoke-1",
        actor_id="actor-demo",
        runtime_session_id="session-demo",
        request_id="request-demo-2",
    )
    if (
        first.error is not None
        or second.error is not None
        or first.replayed
        or not second.replayed
        or demo.executions != 1
        or len(demo.store) != 1
    ):
        raise ToolConfigurationError("double invoke did not collapse to one side effect")
    payload: dict[str, Any] = {
        "agent_version": DEMO_AGENT_VERSION,
        "author_check": "PASS",
        "eval": EVAL_NAME,
        "executions": demo.executions,
        "first_replayed": first.replayed,
        "gateway_id": _GATEWAY_ID,
        "second_replayed": second.replayed,
        "store_rows": len(demo.store),
        "tool": PUT_RECORD,
    }
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if _ARN_MARKER in text or body in text:
        raise ToolConfigurationError("refusing to write evidence that contains a payload or resource identifier")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{EVAL_NAME}.json"
    path.write_text(text, encoding="utf-8")
    return path

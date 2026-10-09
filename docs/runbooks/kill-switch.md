# Kill switch

Turn an agent, a tool, or a source off without a new image. The front door reads the switch **before** it counts quota or starts a Runtime session. Switch off means the call is refused (`switched_off`), no session starts, and an `refused` audit row is written.

Sources: `agentcore_front_door.cli` and the switch rows in the front-door state table. The shape follows the governance switches in aws-samples/sample-agent-platform-with-agentcore (MIT-0).

## When to pull it

| Scope | Use when | Command |
| --- | --- | --- |
| `agent` | The agent is producing wrong or unsafe answers, or a release must stop immediately | `agentcore-front-door switch off agent <pattern> --reason "..." --by <you>` |
| `tool` | One tool is the problem and the rest of the agent can stay up | `agentcore-front-door switch off tool <tool> --reason "..." --by <you>` |
| `source` | Chat is fine, but jobs / events / evals must stop (or the reverse) | `agentcore-front-door switch off source job --reason "..." --by <you>` |

`--reason` is required when switching off. Switching on does not need one: `agentcore-front-door switch on agent <pattern> --by <you>`.

`agentcore-front-door switches` lists every row that has been set. Table names come from `FRONT_DOOR_STATE_TABLE` (and `FRONT_DOOR_AUDIT_TABLE` is not written by this CLI).

## Check first

1. The alarm that paged you. Runtime `SystemErrors` / `Throttles` / p99: the runtime log group and the slow trace. Front-door 5xx: `/aws/lambda/<prefix>-front-door-chat`. A flood of `switched_off` in the audit table means someone already pulled this switch.
2. The `release_id` on the last `completed` audit row. If the errors started with a release, prefer [rollback](README.md#rollback) of the named endpoint, then pull the agent switch only if rollback is not enough.
3. In-flight sessions. The switch stops **new** calls. A warm microVM keeps going until the lease expires or you stop it: `agentcore-front-door stop-session --runtime-arn "$RUNTIME_ARN" --endpoint "$ENDPOINT" --session "$SESSION_ID"`. That is `StopRuntimeSession`. The next call through the front door sees the switch.

## After it is off

- Tell the people on `alert_route` (the pattern's `pattern.yaml`) what you switched and why.
- Leave the reason on the switch row. Do not flip it back without a new release or a documented false alarm.
- A Cedar `forbid` is the right tool when **one** action should stay off across releases. The kill switch is the fast stop; Cedar is the lasting one.

## What this does not do

It does not change IAM, does not roll back an endpoint, and does not drain jobs that already hold a session lease. It does not call AWS unless you run `stop-session`.

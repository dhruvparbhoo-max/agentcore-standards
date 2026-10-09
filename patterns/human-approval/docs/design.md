# Human approval

- Pattern name and folder: `human-approval`, `patterns/human-approval/`.
- Owner: `platform-team@example.com`.
- Autonomy and risk tier: `assistant`, `medium` (one reviewer).
- Framework and trigger: `create_agent`, `none`.
- `deployment: docker`. Images: the agent image, plus the Gateway tool image `submit_change`.
- Acts as: `user`.
- Session lifetime: chat defaults, 5 minutes idle and 30 minutes maximum.

## Main flow and where state lives

The caller reaches the front door, then the runtime. A request to change something selects `submit_change`. The loop interrupts (the hook). `pause_for_human` opens a token bound to the tool name, the argument hash, and the actor. The handler has not run. A person who is not the actor calls `decide`. `resume` spends the token once and then records the change. A rejection never records it.

There is no job row (`trigger: none`). The waiting token lives in the approval store (in-memory locally; a job row in the ambient pattern). Memory is off. Traces carry the release id. The front door writes the audit entry for the call; the approval store is the extra record of who approved the change.

Four asks, same token (`human_approval/ask.py`):

1. **hook** — the loop interrupts. This is what the agent uses.
2. **tool context** — the tool result tells the model a person must decide, then the same pause.
3. **Step Functions wait** — the wait is the job row, not the microVM. A worker resumes through the front door.
4. **MCP elicitation** — the client asks the person. `decide` and `consume` stay ours.

Locally, `uv run pytest patterns/human-approval` runs the golden pause and the resume unit test.

## Failure handling

### Duplicate events

There are no events. A repeated chat message is a new pause with a new token. `submit_change` uses an idempotency key: one key, one stored change. The same key with different arguments is a conflict and stores nothing.

### Retries and timeouts

Throttles to the model are retryable. A schema rejection is fatal. `lifecycle.max_steps` is 8, `lifecycle.timeout_s` is 120, `lifecycle.max_retries` is 3. Primary is EU Claude Sonnet; fallback is EU Claude Haiku.

### Stuck approval

The token lasts `approval.expire_s` (86400 seconds). One reviewer (`risk_tier: medium`). Silence is a no: an expired token does not spend, and the change is not recorded. This chat pattern does not start a new session after the microVM is gone; that resume path is the ambient pattern's job row. The Step Functions ask is written for that case and still uses this token.

### Other failures worth naming

- The actor cannot approve their own change.
- A blocked input returns "I can't help with that request."
- A call without the actor header is refused.

## Expected load and cost

Design assumption, no traffic yet: tens of change requests a day, one pause per request, the microVM does not wait for the person. `cost.max_usd_per_run` is 0.25, `cost.monthly_cap_usd` is 50, `cost.on_cap` is `pause`. Holding a session open while a person decides would be the expensive mistake; this pattern does not do that on the hook path. A Step Functions wait holds the job row instead.

## Session budget

It uses one session per conversation, and it does not start specialist sessions.

## Security and trust boundaries

The agent acts as the user. `submit_change` is the only Cedar permit. User text is tagged and guarded. The data region is `eu-west-2`. The kill switch for this agent stops new calls at the front door; an already-open token still expires. The session header is `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`. The pattern does not run model-written code.

## When to pick a different pattern

- Use policy Q&A when the job is to cite documents, not to change anything.
- Use the ambient pattern when an event should become a job that can wait overnight.

The golden cases are in `eval/golden_set.json`: pause on change, no tool on a question, blocked injection. Resume and "actor cannot approve" are unit tests, because the golden scorer only calls `run`.

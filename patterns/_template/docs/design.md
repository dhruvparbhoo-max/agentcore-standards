# Template pattern

- Pattern name and folder: `_template`, `patterns/_template/`.
- Owner: `platform-team@example.com` (replace when you copy the folder).
- Autonomy and risk tier: `assistant`, `low`.
- Framework and trigger: `create_agent`, `none`.
- `deployment: docker`. The pattern owns one image: the agent image built from `agent/Dockerfile` on `docker/base-agent`.
- Acts as: `user`.
- Session lifetime: chat defaults, 5 minutes idle and 30 minutes maximum.

## Main flow and where state lives

The caller reaches the front door, which checks identity, the session binding, quotas, and the kill switch, then calls the runtime with the session header and the actor header. The runtime screens the text with the guard, tags it as untrusted user text, runs one model turn with no tools, screens the reply, and returns it. There is no job row, because `trigger` is `none` and the call is the job. Memory is off (`memory.enabled: false`, `write_policy: off`). There is no knowledge base. Traces and turn logs go to tracing with the release id on the turn span. The front door writes the audit entry.

Locally, `make local PATTERN=_template` starts the agent with the scripted model in Docker Compose, then posts `events/hello.json` to it.

## Failure handling

### Duplicate events

There are no events. A repeated chat message is a new turn. The template has no send, spend, delete, or change tools, so no tool key is involved.

### Retries and timeouts

Throttles and dropped connections to the model are retryable through the model access layer; a schema rejection is fatal. `lifecycle.max_steps` is 8, `lifecycle.timeout_s` is 120, and `lifecycle.max_retries` is 3. When the step cap is hit the loop ends and the user sees the last answer. The primary model is the EU Claude Sonnet profile; the fallback is the EU Claude Haiku profile. The front door keeps one call in flight per session.

### Stuck approval

The template cannot send, spend, delete, or change, so it never pauses. The mechanism is in the library page.

### Other failures worth naming

A blocked input returns "I can't help with that request." A blocked reply returns "I can't share that answer." A call without the actor header is refused before the loop runs.

## Expected load and cost

Design assumption, no traffic yet: a few hundred turns a day, one model call per turn, no tools. `cost.max_usd_per_run` is 0.25, `cost.monthly_cap_usd` is 50, `cost.on_cap` is `pause`. The user quota at the front door is the first limit a heavy user hits.

## Session budget

It uses one session per conversation, and it does not start specialist sessions.

## Security and trust boundaries

The agent acts as the user and has no on-behalf-of scopes, because it calls no tools. The Runtime role holds only model access. User text is tagged and guarded before the model sees it. `policies/tools.cedar` permits no tools. `schemas/answer.json` is the output shape. Personal data can appear in user text; the guard redacts email addresses and keys before the model, and the log group masks email and IP addresses. The data region is `eu-west-2`. The template reads no secrets. The kill switch for this agent stops every call at the front door. The session header is `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`, and the header allowlist is in the generated `agentcore.json`. The template does not run model-written code.

## When to pick a different pattern

- Use a workflow when the steps never change.
- Use `framework: harness` when the pattern is config, tools, and a prompt.
- Open the policy Q&A pattern when answers must cite documents.
- Open the human approval pattern when the agent must send, spend, delete, or change.

The golden cases are in `eval/golden_set.json`: the echo turn, the blocked instruction override, and the redacted email address.

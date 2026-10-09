# Policy Q&A

- Pattern name and folder: `policy-qa`, `patterns/policy-qa/`.
- Owner: `platform-team@example.com`.
- Autonomy and risk tier: `assistant`, `low`.
- Framework and trigger: `create_agent`, `none`.
- `deployment: docker`. The pattern owns one image: the agent image built from `agent/Dockerfile` on `docker/base-agent`.
- Acts as: `user`.
- Session lifetime: chat defaults, 5 minutes idle and 30 minutes maximum.

## Main flow and where state lives

The caller reaches the front door, which checks identity, the session binding, quotas, and the kill switch, then calls the runtime with the session header and the actor header. The actor id is `{tenant}/{role}/{user}` from the verified login.

The runtime screens the user text with the guard. A trusted wrapper (`policy_qa.knowledge`) then retrieves over a Gateway knowledge-base target (locally: `agentcore_tools.Corpus`) **after** filtering to this tenant and role. The model never chooses the filter and there is no `search_policies` tool. Passages are tagged `<untrusted source="document">`. If retrieve is empty, the wrapper returns `I couldn't find this in the policies` and does not call the model. If it hits, the loop answers and must cite passage ids.

There is no job row (`trigger: none`). Memory is off. Documents live in the knowledge base (the messy fixture set in `knowledge.py` for local and eval). Traces carry the release id. The front door writes the audit entry.

Locally, `uv run pytest patterns/policy-qa` runs the golden set through the scripted model. `make local` still fronts the template agent.

## Failure handling

### Duplicate events

There are no events. A repeated chat message is a new retrieve. This pattern does not send, spend, delete, or change, so no tool key is involved.

### Retries and timeouts

Throttles and dropped connections to the model are retryable through the model access layer; a schema rejection is fatal. `lifecycle.max_steps` is 8, `lifecycle.timeout_s` is 120, and `lifecycle.max_retries` is 3. Primary is the EU Claude Sonnet profile; fallback is EU Claude Haiku. The front door keeps one call in flight per session.

### Stuck approval

This pattern cannot send, spend, delete, or change, so it never pauses. The mechanism is in the library page.

### Other failures worth naming

- Retrieve empty: the user sees `I couldn't find this in the policies`.
- Two leave policies disagree: the answer cites both `HR-Leave-2024` and `HR-Leave-2019` so a wrong source fails the score.
- A finance passage is hidden from `employee`. A Globex passage is hidden from Acme.
- Blocked input: `I can't help with that request.`
- A call without the actor header is refused before retrieve.

## Expected load and cost

Design assumption, no traffic yet: a few hundred questions a day, one retrieve plus at most one model call per turn, no tools. `cost.max_usd_per_run` is 0.50, `cost.monthly_cap_usd` is 200, `cost.on_cap` is `pause`. The user quota at the front door is the first limit a heavy user hits. Retrieval that returns nothing is cheap: no model call.

## Session budget

It uses one session per conversation, and it does not start specialist sessions.

## Security and trust boundaries

The agent acts as the user and has no on-behalf-of scopes. The Runtime role holds model access and, in a live deploy, retrieve on this pattern's knowledge-base target. User text and documents are tagged and guarded. `policies/tools.cedar` permits no tools. `schemas/answer.json` is the output shape. The data region is `eu-west-2`. The kill switch for this agent stops every call at the front door. The session header is `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`. The template does not run model-written code.

The filter is `knowledge.filter_from: verified-login`. Tenant and role come from the actor id the front door set, not from the prompt.

## When to pick a different pattern

- Use a workflow when the steps never change and no retrieve is needed.
- Use the human-approval pattern when the agent must send, spend, delete, or change.
- Use the ambient pattern when an event should become a job.

The golden cases are in `eval/golden_set.json`: source-backed leave, a messy conflict, the empty sentence, a finance-only retrieve, and a blocked injection. `eval.groundedness` is 0.7.

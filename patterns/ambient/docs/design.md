# Ambient

- Pattern name and folder: `ambient`, `patterns/ambient/`.
- Owner: `platform-team@example.com`.
- Autonomy and risk tier: `autonomous`, `medium` (one reviewer).
- Framework and trigger: `create_agent`, `event`.
- `deployment: docker`. Images: the agent image, plus the Gateway tool image `submit_change`.
- Acts as: `service`, with a stored consent record on the event (`consent_ref`).
- Session lifetime: 30 minutes idle and 4 hours maximum. That is longer than chat because a job attempt may run tools before the pause. The wait for a person is not this lifetime; it is the job row.

## Main flow and where state lives

An event hits `accept_event`. The store does a conditional create on source plus event id. If the row exists, the trigger stops. If it is new, the status is `queued`. `run_job` sets `running`, starts a session through the same API the front door would call (locally `AgentSession.run`; in a deploy, the front door), and either marks `succeeded` or `waiting_for_approval` with the token id on the row.

The agent does not use the job row as a notebook. Memory is off. Checkpoints are the prompt stored on the row so a later session can resume after the microVM is gone. Resume still goes through the front door.

Locally, `uv run pytest patterns/ambient` runs the duplicate-event test, the pause-on-the-job-row test, and the golden set.

## Failure handling

### Duplicate events

The idempotency key is source plus event id. A second delivery of `invoices` / `evt-invoice-pack-0001` returns the existing job and does not start another session. `submit_change` also has a tool-level idempotency key.

### Retries and timeouts

Throttles to the model are retryable. A schema rejection is fatal. `lifecycle.max_steps` is 8, `lifecycle.timeout_s` is 120, `lifecycle.max_retries` is 3. Primary is EU Claude Sonnet; fallback is EU Claude Haiku. A failed attempt increments `attempt` on the row.

### Stuck approval

The token lasts `approval.expire_s` (86400 seconds). One reviewer. Silence is a no: the sweeper (not built here) would mark the job `failed` and not perform the change. A person who decides later causes a **new** session through the front door, loading the checkpoint. This change records that path in unit tests by calling `resume` on the same in-process session.

### Other failures worth naming

- Event text that looks like an instruction override is blocked.
- A terminal job (`succeeded` / `failed` / `cancelled`) cannot be run again.
- A call without the actor header is refused.

## Expected load and cost

Design assumption, no traffic yet: tens of events a day, one session per new event, a change pauses so the microVM can stop. `cost.max_usd_per_run` is 0.50, `cost.monthly_cap_usd` is 200, `cost.on_cap` is `pause`. Holding the microVM open overnight would be the expensive mistake; the job row holds the wait.

## Session budget

One session per job attempt. It does not start specialist sessions. If volume grew to one event a minute with a 30 minute idle timeout, concurrent microVMs would be the session quota; shorten idle or drain faster. That product is an assumption, not a measurement.

## Security and trust boundaries

The agent acts as a service. Consent is the `consent_ref` on the event; `on_behalf_of` is the user the work is for. The Runtime role holds model access and `submit_change`. Event payloads are untrusted and guarded. Cedar permits only `submit_change`. The data region is `eu-west-2`. The kill switch for this agent stops new jobs at the front door. The session header is `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`. The pattern does not run model-written code.

## When to pick a different pattern

- Use human-approval when a person is already in a chat and asks to change something.
- Use policy Q&A when the job is to cite documents.
- Use a workflow when the steps never change and no model is needed.

The golden cases are in `eval/golden_set.json`: a queued non-change, a pause on change, a blocked injection. Duplicate events and resume-from-the-job-row are unit tests.

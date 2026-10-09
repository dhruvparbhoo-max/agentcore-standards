# agentcore-front-door

The only way to start an AgentCore Runtime session. Chat, API, job, schedule, event, and eval callers all go through `FrontDoor.call`. The rules it enforces are in [docs/design/library.md](../../docs/design/library.md) "Front door".

## What one call does

1. **Who is calling.** A person: the bearer token is verified against the issuer's JWKS (RS256, issuer, audience, `token_use`). User id, team, tenant, and roles come from claims, never from the body. A job: the service identity and the stored consent on the job row. A job with no consent record does not run.
2. **Session binding.** The session id is bound to the caller with an HMAC tag. No id gets a new one. An id this caller owns is returned unchanged. An id carrying another caller's tag is refused. A raw id shorter than 33 characters (or the pattern's `session_id_min`) is refused.
3. **One call in flight per session.** A lease row with an expiry. A second call while the first runs gets `409 session_busy`.
4. **Kill switches** per agent, per tool, and per source. Read before quotas count, so a switched-off agent uses up nobody's quota. Runbook: [docs/runbooks/kill-switch.md](../../docs/runbooks/kill-switch.md).
5. **Quotas and rate limits** per user, team, and agent per day, and per user per minute. Atomic counters, counted before the call.
6. **Caps.** Turns per session (`lifecycle.max_turns`). Monthly spend for the agent (`cost.monthly_cap_usd`), and for each user and team (environment config). Steps (`lifecycle.max_steps`) and spend per run (`cost.max_usd_per_run`) are enforced inside the agent and checked again here from the usage it reports; a breach is flagged on the audit row.
7. **On-behalf-of token** when `identity.acts_as` is `user` and the pattern names credential providers: `GetWorkloadAccessTokenForJWT`, then `GetResourceOauth2Token` with `ON_BEHALF_OF_TOKEN_EXCHANGE`. Tokens ride to the agent on `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Obo-Tokens`. They are never logged or audited; the audit row names the providers only.
8. **Runtime call** to the pattern's named endpoint, with the actor on `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id`.
9. **Audit and cost.** An `accepted` row is written before Runtime is called; if it cannot be written, the call does not start. Then a `completed` row (latency, turn, release id, model calls, cost, breaches) and a cost record. Refusals are audited too. The audit table is append-only and the front door role holds `PutItem` on it and nothing else.

## Model access layer

`ModelAccess` is the one way an agent calls Bedrock: capped exponential backoff with jitter through `agentcore_recovery`, a `Retry-After` the service sends, the fallback profile when the primary stops, and a check that both ids are `eu.` geographic profiles when `region_profile: eu` (UK workloads in eu-west-2 use the EU profile). Each agent's own model key is an application inference profile tagged with the team (`infra/constructs` `AgentModelProfile`); its id arrives in `AGENTCORE_MODEL_PROFILE_ARN`. LangChain and Strands adapters live in `agentcore_agent.models`.

## Running it

| Handler | Function | Caller |
| --- | --- | --- |
| `agentcore_front_door.handlers.chat.handler` | `POST /agents/{agent}/invoke` on the HTTP API | People, through the JWT authorizer |
| `agentcore_front_door.handlers.job.handler` | Direct Lambda invoke | The triggers worker, with IAM |

The image is `primitives/front-door/Dockerfile` (`lambda-front-door` in `scripts/images.py`), on the shared Lambda base. The CDK construct is `agentcore_constructs.FrontDoor` (tables, JWT HTTP API, least-privilege role). Operators use `agentcore-front-door switch off agent <name> --reason ... --by ...`. Runbooks: [kill-switch](../../docs/runbooks/kill-switch.md), [quotas](../../docs/runbooks/quotas.md).

## Sources

Copied from aws-samples/sample-agent-platform-with-agentcore (MIT-0): session binding, governance counters, audit rows, the JWKS verifiers, and the single invocation pipeline. Token usage and retryable codes from aws-samples/sample-eval-first-building-enterprise-agents-with-agentcore (MIT-0). The on-behalf-of calls match the AgentCore Python SDK's `IdentityClient` (Apache-2.0). See [docs/attribution/third-party.md](../../docs/attribution/third-party.md).

## What has not been run

Nothing here has called AWS. The tests use in-memory fakes and DynamoDB Local. There is no live Runtime PASS.

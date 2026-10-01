# Capability map: minimal-agent

Status: lane A. Session, tools, Memory, Gateway, and guardrails are intentionally absent.

## Entrypoint

| Item | Value |
| --- | --- |
| Module | `minimal_agent.entrypoint` |
| App | `BedrockAgentCoreApp` from `bedrock-agentcore` |
| Handler | `invoke(payload, context)` registered with `@app.entrypoint` |
| Local serve | `PYTHONPATH=templates/minimal-agent/src uv run python -m minimal_agent` (port 8080) |
| Version | `0.1.0` (`AGENT_VERSION` and the template `pyproject.toml`) |

## Drive it

Input payload: `{"prompt": "<non-empty string>"}`. Any other JSON type for `prompt` raises `ValueError` before a model span.

In-process eval driver: `MinimalAgentHarness()`. Service driver: `MinimalAgentHarness.for_agentcore_runtime()` when `AGENTCORE_RUNTIME_ARN`, `AWS_REGION`, credentials, and `AGENTCORE_SPAN_LOG_GROUP` are set in the environment.

Actor id on the in-process path is request header `x-agentcore-actor-id`, set by `handle_turn`. The session package will own actor identity later. Until then a hosted Runtime call that does not send the header logs `actorId` as `unknown`.

## Observable

Eval `minimal-agent.golden-turn`:

- Turn 1 result is `pong:ping`. Turn 2 result is `pong:again`. Same `runtimeSessionId`.
- Spans: `agent.turn` parent, `model.invoke` child, shared trace id.
- Attributes on the turn: `agent.version`, hashed `runtime.session_id`, `cost.tokens` ≥ 1, `cost.usd_estimate` present (0 until a priced model client exists).
- Log line includes `runtimeSessionId`, `actorId`, `agentVersion`, `requestId`, `latencyMs`, `errorClass: null`.

## Not on this template

No tools, no Gateway target, no Memory namespace, no approval gate, no guardrail id. Those maps belong to later templates.

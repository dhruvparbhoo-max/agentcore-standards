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

Judge process, from the repo root: `PYTHONPATH=templates/minimal-agent/src uv run python -m minimal_agent.judge --evidence-dir evidence/judge`. Add `--harness runtime` for the service. Evidence is `evidence/judge/verdict.json` and `evidence/judge/minimal-agent.golden-turn.json`. The PASS path is [docs/eval-pass-path.md](../eval-pass-path.md).

Actor id on the in-process path is request header `x-agentcore-actor-id`, set by `handle_turn`. `AgentCoreRuntimeHarness` sends `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id`. The hosted app reads that header after it is lowercased. A call that sends neither logs `actorId` as `unknown`.

## Observable

Eval `minimal-agent.golden-turn`:

- Turn 1 result is `pong:ping`. Turn 2 result is `pong:again`.
- Spans: `agent.turn` parent, `model.invoke` child, shared trace id.
- Attributes on the turn: `agent.version`, hashed `runtime.session_id`, raw `session.id` (CloudWatch filter key), `cost.tokens` ≥ 1, `cost.usd_estimate` 0, `cost.source` `length-heuristic`. That cost label is the pong path, not a billing check.
- Log line includes hashed `runtimeSessionId` (not the raw id), `actorId`, `agentVersion`, `requestId`, `latencyMs`, `errorClass: null`.

## Not on this template

No tools, no Gateway target, no Memory namespace, no approval gate, no guardrail id. Those maps belong to later templates.

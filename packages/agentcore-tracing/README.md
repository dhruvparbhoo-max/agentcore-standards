# agentcore-tracing

OpenTelemetry conventions for AgentCore agents (DESIGN §2.5). Version 0.1.0.

| Span | Name |
| --- | --- |
| Root, one per user turn | `agent.turn` |
| Model call | `model.invoke` |
| Tool call | `tool.<name>` |
| Memory | `memory.write`, `memory.retrieve` |
| Gateway | `gateway.call` |
| Guardrail | `guardrail.check` |

Required attributes on `agent.turn`: `agent.version`, `runtime.session_id` (SHA-256 prefix, not the raw id), `cost.tokens`, `cost.usd_estimate`.

`missing_required_attributes` is the CI check. A present zero counts as present. The default USD rate is 0 until a model client reports usage.

Structured logs go to logger `agentcore.turn` as one JSON object with `runtimeSessionId`, `actorId`, `agentVersion`, `requestId`, `latencyMs`, `errorClass`, and `toolName` when a tool ran.

`use_binding` captures spans for an in-process eval. When no binding is set, `get_tracer` uses the process provider so AgentCore Runtime's ADOT exporter still receives spans.

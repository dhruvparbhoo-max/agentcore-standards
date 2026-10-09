# agentcore-tracing

OpenTelemetry conventions for AgentCore agents. See [the library design](../../docs/design/library.md). Version 0.1.0.

| Span | Name |
| --- | --- |
| Root, one per user turn | `agent.turn` |
| Model call | `model.invoke` |
| Tool call | `tool.<name>` |
| Memory | `memory.write`, `memory.retrieve` |
| Gateway | `gateway.call` |
| Guardrail | `guardrail.check` |

Required attributes on `agent.turn`: `agent.version`, `runtime.session_id` (SHA-256 prefix, not the raw id), `cost.tokens`, `cost.usd_estimate`. `session.id` is also set to the raw id so CloudWatch span collection can filter on it. `cost.source` labels how the numbers were produced. The default is `length-heuristic` at zero USD. That is not model-reported usage and it is not a billing proof. See [the library design](../../docs/design/library.md).

`missing_required_attributes` is the CI check for the four required names. A present zero counts as present. It does not require `cost.source`.

Structured logs go to logger `agentcore.turn` as one JSON object. `runtimeSessionId` is the same hash as span `runtime.session_id`. The raw id is not written next to `actorId`. The other fields are `actorId`, `agentVersion`, `requestId`, `latencyMs`, `errorClass`, and `toolName` when a tool ran.

`use_binding` captures spans for an in-process eval. When no binding is set, `get_tracer` uses the process provider so AgentCore Runtime's ADOT exporter still receives spans.

# Capability map: shared shelf

Status: in-process libraries. No Gateway, Memory service, or Runtime PASS.

| Package | Drive it | Observable |
| --- | --- | --- |
| `agentcore-guardrails` | `Guard().apply_input` / `apply_output` / `screen_memory_write` | Injection and secret-shaped text return `Blocked` and the reason does not contain the text. Email text returns `Sanitized` with the address removed. `require_service=True` without a backend returns `guardrail_unconfigured`. |
| `agentcore-memory` | `MemoryClient(Guard(), agent_version=..., environment=...).create_event` | A blocked write raises `MemoryWriteDenied` and `list_session_events` is empty. A promoted record is `tier=ltm`. `retrieve` for another actor is empty. Hits say `method=lexical`. |
| `agentcore-identity` | `require_actor_id(headers)` | Custom actor header wins. The workload user header alone raises `ActorMissing`. Two different session ids raise `SessionMismatch`. |
| `agentcore-approvals` | `ApprovalGate.issue` then `decide` then `consume` | Pending, self-approval, mismatch, expiry, and a second consume raise `ApprovalError`. The audit list records the transitions. |
| `agentcore-context` | `assemble_context(..., state_bar=StateBar(...))` | The rendered bar contains `tools=` and `errors=`. Over-budget tool text is named in `omissions`. `estimate_source` is `length-heuristic`. An unscreened memory line cannot be constructed. |
| `agentcore-recovery` | `run_with_recovery` | A fatal outcome runs once. An open circuit's next call has `attempts == 0`. A full in-flight gate returns `stop_reason=in_flight` without calling. |
| `agentcore-completion` | `CompletionVerifier(verifier_id=...).check(claim, evidence)` | The same proposer and verifier id raises `SamePartyError`. Open todos, tool errors, and missing citations set `accepted` false. |
| `agentcore-tools` catalog | `ToolCatalog(registry).index` then `load` | Index cards have no `inputSchema`. `load` returns one. `invoke_tool` is still denied until `Policy.permit`. |
| `agentcore-tools` cite | `Corpus.retrieve` | A token overlap returns a `Citation` whose `render()` names the passage id. An unrelated query returns `()`. |
| `agentcore-langchain` | `registry_callables` inside `bind_turn` | An unpermitted tool returns a `fatal` code and the handler count stays 0. `create_runtime_agent` passes those callables through to `create_agent`. |

Domain templates are not on this map. They import this shelf when they are written.

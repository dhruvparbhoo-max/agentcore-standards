# Capability map: agent-with-tools

Status: lane F template. It imports the shared shelf, including `agentcore-langchain`. Offline judge is implemented. No live Runtime PASS is recorded.

## Entrypoint

| Item | Value |
| --- | --- |
| Module | `agent_with_tools.entrypoint` |
| App | `BedrockAgentCoreApp` from `bedrock-agentcore` |
| Handler | `invoke(payload, context)` registered with `@app.entrypoint` |
| Local serve | `PYTHONPATH=templates/agent-with-tools/src uv run python -m agent_with_tools` (port 8080) |
| Version | `0.1.0` (`AGENT_VERSION`) |
| Graph | `agentcore_langchain.build_langchain_agent` around `create_agent` |
| Hosted model | `ChatBedrockConverse`, default id `us.anthropic.claude-sonnet-4-6`, override `BEDROCK_MODEL_ID` |

## Tools

| Tool | Gateway target | Side effect | Policy |
| --- | --- | --- | --- |
| `fetch_invoice` | `billing` | Read | Permitted for `0.1.0` only |
| `submit_invoice_note` | `billing` | Write, idempotent | Same allowlist. Human approval before the handler. |

Local gateway id when `AGENTCORE_GATEWAY_ID` is unset: `billing-desk-local`. Cedar actions: `billing___fetch_invoice`, `billing___submit_invoice_note`.

Tenant and user come from the payload or headers, then `CallerContext`. The LangChain tool schema does not include `tenant_id`.

## Approval

`agent_middleware` puts `HumanInTheLoopMiddleware` first. That is the outer gate. `fetch_invoice` is omitted from `interrupt_on` (auto). `submit_invoice_note` allows `approve` and `reject`. The pause issues an `ApprovalGate` token. Resume sends `decision` and `approver_id` on the same `runtimeSessionId` (`thread_id`). The approver must not be the actor. The write tool consumes the token before `invoke_tool`.

## Memory, guard, context, recovery

`Guard.apply_input` screens the prompt. `Guard.apply_output` screens the reply. Email shapes become `[redacted-email]`. `PIIMiddleware` still masks a credit card; that mask is not the guardrail.

`MemoryClient.create_event` stores the screened user and assistant text. The namespace comes from the agent version and `local`. `AGENTCORE_MEMORY_ID` selects LangGraph's `AgentCoreMemorySaver` for the thread checkpointer only. Without it the checkpointer label is `in-memory-not-production`. That saver is not `MemoryClient`.

`ShelfContextMiddleware` calls `assemble_context` with a `StateBar`. Retryable registry results go through `run_with_recovery` (two attempts, no sleep). Fatal results are not retried.

## Drive it

Offline judge (scripted model, exit 0 on PASS):

```bash
PYTHONPATH=templates/agent-with-tools/src uv run python -m agent_with_tools.judge --evidence-dir evidence/judge-tools
```

Runtime judge (exit 1 when settings are missing):

```bash
PYTHONPATH=templates/agent-with-tools/src uv run python -m agent_with_tools.judge --harness runtime --evidence-dir evidence/judge-tools
```

Evidence directory: `evidence/judge-tools/`. The minimal-agent evidence directory stays `evidence/judge/`.

## Observable

| Eval | Proves |
| --- | --- |
| `agent-with-tools.invoice-read` | `INV-1001` for `acme` is `1250.00` OPEN. No email leak, no globex amount, one fetch, `gateway.call` under `tool.fetch_invoice`. |
| `agent-with-tools.invoice-note` | Write pauses with zero notes. Approve stores one. Same key returns `duplicate=true` and the handler count stays 1. |
| `agent-with-tools.policy-deny` | Agent version `0.9.0` gets `invoice-error:policy_denied`. Handler does not run. No `gateway.call`. |
| `agent-with-tools.fatal-read` | `INV-4040` is `invoice_not_found` after one handler run. |
| `agent-with-tools.retry-read` | One retryable failure, then the acme line. Handler count 2. |
| `agent-with-tools.runtime-smoke` | Service path only. Status `completed` or `interrupted`, non-empty text, `agent.turn` cost attributes. Not a string match against the hosted model. |

Turn spans require `agent.version`, hashed `runtime.session_id`, `cost.tokens`, and `cost.usd_estimate`.

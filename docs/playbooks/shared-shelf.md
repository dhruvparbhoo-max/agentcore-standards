# Shared shelf

Copy these packages. Do not paste them into a pattern, and do not start a pattern until the import line is the package.

This shelf has no independent Runtime PASS. Unit tests are the offline check. A live Gateway or Runtime call that lacks its settings is not a pass.

## What to import

| Need | Import |
| --- | --- |
| Deny-by-default tools | `agentcore_tools.ToolRegistry`, `Policy` |
| Shorten a tool result | `agentcore_tools.compact_tool_output` |
| Retrieve and cite | `agentcore_tools.Corpus` |
| Show names, then load one schema | `agentcore_tools.ToolCatalog` |
| Screen input, output, and memory | `agentcore_guardrails.Guard` |
| Remember after the screen | `agentcore_memory.MemoryClient` |
| Actor and session headers | `agentcore_identity.require_actor_id`, `require_session_id` |
| Gate a write | `agentcore_approvals.ApprovalGate` |
| Build the prompt | `agentcore_context.assemble_context`, `StateBar` |
| Retry without a storm | `agentcore_recovery.run_with_recovery` |
| Decide the loop is done | `agentcore_completion.CompletionVerifier` |
| LangChain `create_agent` | `agentcore_langchain.create_runtime_agent` |

## Turn order

1. Read the actor and the session from headers. A missing actor is an error. Do not treat the workload user header as the actor.
2. `Guard.apply_input` on the user text. A block stops the turn.
3. Build a `StateBar` (open todos, tool count, error count, circuit). `assemble_context` keeps that bar, the system text, and the user turn when the budget is tight. Tool results are dropped first.
4. `ToolCatalog.disclose` returns cards. `load` one schema when the model must call it. Disclosure does not permit the tool.
5. Call `invoke_tool`. The policy starts empty. Wrap retryable failures in `run_with_recovery`. Do not retry a fatal result. An open circuit does not call the tool.
6. A side-effecting tool that needs a person calls `ApprovalGate.consume` inside the handler, after `decide` from a different party. No token, no write.
7. `Guard.apply_output` on the text the user will see.
8. `MemoryClient.create_event` for anything that should be remembered. A block stores nothing. `promote` is the long-term step. `retrieve` only returns that actor's records, and the score is lexical.
9. Hand the claim and the evidence to a `CompletionVerifier` whose id is not the proposer's.

`agentcore_langchain.registry_callables` are the tools passed to `create_agent`. They call `invoke_tool` and compact the string the model sees. Bind a turn with `turn_from_headers` first. The system prompt should be `AssembledContext.as_system_prompt()`.

## Lambda and MCP

Lambda is the path that syncs. Register tools, `add_lambda_target`, `bind_gateway`, then `AgentCoreGatewayClient.sync` when the gateway environment names are set. The handler is `make_lambda_handler`. Idempotency is the registry key plus a put-if-absent inside the handler.

`McpServerTarget.to_configuration` still raises. Naming an MCP server does not publish it. Use the catalog for progressive disclosure on the Lambda target. Do not pretend an MCP target synced.

## Accounts

The [library design](../design/library.md) keeps evals in the dev account and isolates them with agent versions, namespaces, and IAM paths. A separate dev, staging, and prod account layout is later work. This shelf does not add a second stack and does not create Memory in infrastructure. Memory writes go through `MemoryClient` and the guard. They do not go through Gateway.

## What is not proven

No live `InvokeAgentRuntime` PASS. No live `ApplyGuardrail` PASS. The Bedrock backend blocks when it is required and missing. Cost figures on this shelf are the length heuristic, not a bill.

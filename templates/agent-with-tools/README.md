# agent-with-tools

Invoice desk on Amazon Bedrock AgentCore Runtime. Version 0.1.0. An application, not a published library.

The graph is LangChain `create_agent`. Shared assembly, compaction, and approval parsing live in `agentcore-langchain`. Tools go through `agentcore-tools`: Gateway target `billing`, deny-by-default policy, and an idempotency key on `submit_invoice_note`. The template does not keep a second ledger.

The desk imports the shelf. `Guard` screens the prompt and the reply. `MemoryClient` stores those screened strings. `ApprovalGate` issues a token when a write pauses; `approver_id` must be a different party, and the write tool consumes the token. `assemble_context` builds the model prompt with a `StateBar`. Retryable registry calls use `run_with_recovery`. `PIIMiddleware` still masks a card number. That mask is not the guardrail.

`AGENTCORE_MEMORY_ID` selects LangGraph's thread checkpointer only. Otherwise the label is `in-memory-not-production`. That saver is not `MemoryClient`.

The invoice catalog and the note map live in the process that calls `invoke_tool`. A Gateway Lambda is a different process. `sync_billing_gateway` publishes this handler as target `billing`. Do not point that sync at a function whose code is a different tool. Live Gateway MCP invocation is not what the golden eval calls. Durable DynamoDB is not claimed.

This README is not a Runtime PASS. The offline judge is green. A live `InvokeAgentRuntime` PASS has not been run in this change.

## Drive it

Local serve, the same entrypoint Runtime hosts:

```bash
PYTHONPATH=templates/agent-with-tools/src uv run python -m agent_with_tools
```

`POST /invocations` body:

| Field | Required | Meaning |
| --- | --- | --- |
| `prompt` | On a new turn | Non-empty string. A list or object is `status: rejected` before the graph runs. |
| `decision` | On a resume | `approve` or `reject`. `edit` and `respond` raise. |
| `approver_id` | On a resume | Reviewer. Must differ from the actor. The actor cannot approve the write. |
| `tenant_id` | Yes | Caller tenant. The model cannot set it. Header `x-agentcore-tenant-id` is the fallback. |
| `user_id` | Falls back to the actor | Header `x-agentcore-user-id`, then the actor id from `agentcore-identity`. |

A write returns `status: interrupted` and an `interrupt` object. Resume on the same session with `decision`. Reject does not store a note.

Tools the model can call:

| Tool | Side effect | Idempotent | Approval |
| --- | --- | --- | --- |
| `fetch_invoice` | No | Yes | Auto |
| `submit_invoice_note` | Yes | Yes, key plus put-if-absent on `(tenant, invoice, key)` | `approve` or `reject` only |

Same invoice id differs by tenant. `INV-1001` is `1250.00` OPEN for `acme` and `9999.00` for `globex`.

## Offline judge

No AWS credentials. This installs the scripted model and exits 0 on PASS.

```bash
PYTHONPATH=templates/agent-with-tools/src uv run python -m agent_with_tools.judge --evidence-dir evidence/judge-tools
```

Evidence is `evidence/judge-tools/verdict.json` (gitignored). Evals: `agent-with-tools.invoice-read`, `invoice-note`, `policy-deny`, `fatal-read`, `retry-read`. What this proves: the in-process entrypoint, policy deny, approval before the write, and one note for a repeated idempotency key. What it does not prove: a deployed microVM, CloudWatch spans, or IAM.

## Runtime judge

```bash
PYTHONPATH=templates/agent-with-tools/src uv run python -m agent_with_tools.judge --harness runtime --evidence-dir evidence/judge-tools
```

Missing settings write `status: SKIPPED` and the process exits 1. SKIPPED is not PASS. The workflow job `agent-with-tools-runtime` uses that exit code. The minimal-agent runtime job fails closed the same way.

Required for a real run:

| Name | Role |
| --- | --- |
| `AWS_REGION` | Dev account region. Evals use that same account. |
| `AGENTCORE_RUNTIME_ARN` | Deployed runtime. Not committed. |
| `AGENTCORE_SPAN_LOG_GROUP` | CloudWatch log group name. Not an ARN in git. |
| `AWS_ROLE_TO_ASSUME` | OIDC role for GitHub Actions. Or use the key pair below. |
| `AWS_ACCESS_KEY_ID` | Key auth when OIDC is not used. Pair with `AWS_SECRET_ACCESS_KEY`. |
| `AWS_SESSION_TOKEN` | Optional. |
| `AGENTCORE_RUNTIME_QUALIFIER` | Optional endpoint qualifier. |

IAM for the judge: `bedrock-agentcore:InvokeAgentRuntime`, `logs:StartQuery`, `logs:GetQueryResults`.

Gateway sync is a separate operator step. The judge stays SKIPPED without the runtime names above even if these are set:

| Name | Role |
| --- | --- |
| `AGENTCORE_GATEWAY_ID` | Gateway to bind before sync. |
| `AGENTCORE_POLICY_ENGINE_ID` | Policy engine that receives the Cedar permits. |
| `AGENTCORE_TOOLS_LAMBDA_ARN` | Lambda whose code is `agent_with_tools.billing.lambda_handler`. |
| `AGENTCORE_GATEWAY_RESOURCE` | Cedar resource token for those permits. |
| `AGENTCORE_MEMORY_ID` | Optional. Selects `AgentCoreMemorySaver`. |
| `BEDROCK_MODEL_ID` | Optional. Default is `us.anthropic.claude-sonnet-4-6`. |

```bash
PYTHONPATH=templates/agent-with-tools/src uv run python -m agent_with_tools.gateway_sync
```

That command prints `synced billing gateway target` and does not print the sync response.

## Deploy

1. Host this entrypoint as `BedrockAgentCoreApp` (`python -m agent_with_tools`, port 8080).
2. Give the runtime role `bedrock:InvokeModel` (or the Converse equivalent) for `BEDROCK_MODEL_ID`, and nothing else it does not need.
3. Deploy `lambda_handler` as its own function. The runtime role does not need to call billing tools directly.
4. Run `gateway_sync` with the four Gateway names. The local policy is already deny-by-default. It does not flip a `LOG_ONLY` engine to `ENFORCE`.
5. Put the runtime behind Gateway inbound auth so callers cannot skip the gateway. This template does not attach that resource policy. The eval protocol still calls `InvokeAgentRuntime`.
6. Set `AGENTCORE_RUNTIME_ARN` and `AGENTCORE_SPAN_LOG_GROUP` for the judge. A stack output from a later infrastructure change maps onto those names. Do not commit the values.

## Practices this template follows

- `create_agent` with a stable system prompt, `context_schema`, and middleware. The first middleware is the outer wrapper, so human approval sits in front of tool retry. [create_agent](https://reference.langchain.com/python/langchain/agents/create_agent), [middleware](https://docs.langchain.com/oss/python/langchain/middleware/overview), [built-ins](https://docs.langchain.com/oss/python/langchain/middleware/built-in), [human-in-the-loop](https://docs.langchain.com/oss/python/langchain/human-in-the-loop), [runtime context](https://docs.langchain.com/oss/python/langchain/runtime), [tools](https://docs.langchain.com/oss/python/langchain/tools).
- `prompt` is a non-empty string before the framework sees it, so a `toolUse` block cannot dispatch a tool. [Runtime security](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-security-best-practices.html), [InvokeAgentRuntime](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-invoke-agent.html).
- Gateway Lambda tool schema and Cedar deny-by-default. [Lambda targets](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-lambda.html), [Policy](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-getting-started.html), [interceptors](https://aws.amazon.com/blogs/machine-learning/secure-ai-agents-with-policy-and-lambda-interceptors-in-amazon-bedrock-agentcore-gateway/). Tenant injection from caller context is the in-process analogue of a request interceptor.
- No-auth gateways are not production. [Inbound auth](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-inbound-auth.html).
- Compaction is deterministic and does not call a model. The system prompt stays the prefix. The state bar counts tool names and the last error code.

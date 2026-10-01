# agentcore-tools

Tool registry and Gateway wiring for AgentCore (DESIGN §2.2). Version 0.1.0.

Agents call `invoke_tool`. Gateway fronts every tool. The policy starts empty, so a call is denied until that agent version is permitted. A forbid wins over a permit. Cedar on the real Gateway uses the same posture: no matching permit is a deny, and a forbid overrides a permit.

The default target is **Lambda**. MCP server targets can be named, and `to_configuration` fails so they are not synced.

## Register and call

```python
from agentcore_tools import Policy, build_demo_registry

demo = build_demo_registry()
policy = Policy()
policy.permit("0.1.0", "put_record")
demo.registry.bind_gateway("gateway-dev", policy=policy)

result = demo.registry.invoke_tool(
    "put_record",
    {"record_id": "rec-1", "body": "hello"},
    agent_version="0.1.0",
    idempotency_key="invoke-1",
)
```

`@registry.tool(name, schema, description, idempotent=True)` is the registration decorator. A side-effecting tool with `idempotent=False` raises `IdempotencyRequired` at registration.

`put_record` is the demo tool. It is side-effecting and idempotent. The handler uses put-if-absent on `record_id`: a second call with the same id returns the original row and does not overwrite it. The registry also requires an idempotency key and replays the first result when that key is repeated. Same key with different arguments is a fatal conflict and does not run the handler. Retryable failures are not cached. Fatal failures are cached. A handler timeout, or a call that exceeds `timeout_ms`, is retryable and includes `backoff_ms`. Fatal results have no backoff.

Schema checks use a JSON Schema subset (object, array, string, number, integer, boolean, properties, required, items). Unknown object properties are rejected unless `additionalProperties` is true. Rejection messages name the path and the expected type. They do not include the rejected value. Breaking schema changes (removed property, type change, new required property) must bump the major in `schema_version`; call `assert_schema_evolution` when a schema changes.

## Attach tools to Gateway

1. Register tools and map them with `add_lambda_target`. `build_demo_registry` does this for `records` / `put_record`.
2. `bind_gateway(gateway_id, policy=Policy())`. Every registered tool must sit on a Lambda target. The policy object stays live: `permit` after bind takes effect on the next call.
3. `invoke_tool` checks the binding, the per-agent-version policy, the schema, and the idempotency key. Denied and invalid calls do not run the handler. A permitted call opens a `tool.<name>` span and a child `gateway.call` span. Logs go through `agentcore.turn` with the hashed session id, actor, agent version, request id, tool name, latency, and error class. Arguments are not logged.
4. On AWS, `AgentCoreGatewayClient.from_env().sync(...)` calls `bedrock-agentcore-control` `create_gateway_target` and `create_policy`.

The Lambda target payload is the Gateway MCP Lambda shape: `lambdaArn` plus `toolSchema.inlinePayload` (`name`, `description`, `inputSchema`). `additionalProperties` is enforced in this package and is not sent. Outbound auth is `GATEWAY_IAM_ROLE` (the gateway role invokes the function). Give that role only the invoke permission it needs, and limit the function resource policy to that role.

Cedar statements use the visible action `target___tool`:

```text
permit(
  principal,
  action == AgentCore::Action::"records___put_record",
  resource == AgentCore::Gateway::"<gateway resource from the environment>"
);
```

`sync` writes a permit for each tool the agent version allows, or a forbid when the tool is forbidden. Tools with neither produce no statement, and Cedar denies them. Statements do not carry the agent version. Keep one policy engine per agent version so an old permit does not outlive that version. `sync` does not delete stale statements.

The Lambda entrypoint is `make_lambda_handler(registry, agent_version=...)`. Gateway passes arguments as the event and `target___tool` in `context.client_context.custom["bedrockAgentCoreToolName"]`. That handler validates the schema and runs the tool. Authorization for that call is Gateway Cedar, already applied before the function runs; `invoke_tool` is the agent-side check. The idempotency key is enforced before the gateway call. The natural key inside `put_record` keeps a retried Lambda invocation from creating a second row.

Environment names for the real control plane (values stay in the environment, never in git):

| Name | Role |
| --- | --- |
| `AWS_REGION` | Control-plane region |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Dev account credentials |
| `AGENTCORE_GATEWAY_ID` | Gateway identifier passed to `bind_gateway` and `sync` |
| `AGENTCORE_POLICY_ENGINE_ID` | Policy engine that receives Cedar statements |
| `AGENTCORE_TOOLS_LAMBDA_ARN` | Lambda function identifier for the target |
| `AGENTCORE_GATEWAY_RESOURCE` | Resource token embedded in Cedar `AgentCore::Gateway::"..."` |

## What a local run proves

`tools.double-invoke` (`write_double_invoke_evidence`) runs two `invoke_tool` calls with one idempotency key and writes counts only: one handler execution, one store row, the second call replayed. Unit tests also cover allow, deny, forbid-over-permit, schema rejection, idempotency conflict, retryable versus fatal errors, and the Lambda control-plane payload against an in-memory client.

`pytest -m runtime` calls `sync` on the real control plane when the variables above are set, and skips when they are not. That test creates the target and the Cedar permit. Live invocation through the Gateway MCP endpoint is outside this marker.

This package does not emit an independent ship verdict. CI green on the unit tests is not PASS. A separate judge still has to run the Gateway path in the dev account.

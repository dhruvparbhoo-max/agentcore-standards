---
name: agentcore-tool-register
description: >
  Register or change a Gateway tool in agentcore-tools. Use when adding a
  tool name, schema, description, or side effect. Covers a goal-shaped
  schema, argument fidelity, deny-by-default, and double-invoke evidence.
---

# Register a Gateway tool

Read [docs/tools/design.md](../../docs/tools/design.md) and `packages/agentcore-tools/README.md`. Idempotent retries are DESIGN §1.6. This skill is the registration checklist around that rule.

## When

You are adding a tool, changing its schema or description, or moving a side effect behind Gateway.

## Steps

1. Name the goal, not the upstream route. Merge tools that differ only by a file type or a cosmetic flag. Split when security, audit, nesting, or a hot path needs its own name.
2. Write the description: when to call it, what it will not do, one concrete parameter example, the return shape, and the cost of a heavy call.
3. Reject bad arguments. If you normalize, say so in the description and return the value the handler used. Do not rewrite or inject arguments silently.
4. Register with `@registry.tool`. A side-effecting tool sets `idempotent=True` and documents the idempotency key (or a precheck-then-confirm when the effect cannot be replayed, such as an outbound payment). `IdempotencyRequired` is the registration failure for a side effect with `idempotent=False`.
5. Leave the policy empty until this agent version is permitted. A forbid wins. Map the tool to a Lambda target before `bind_gateway`. MCP targets can be named; `to_configuration` fails, so they are not synced.
6. Add a double-invoke case: one key, one handler run, one stored row, the second call replayed. Schema rejection and a deny path do not run the handler.
7. Confirm logs omit arguments and include tool name, latency, and error class on `agentcore.turn`. Then **agentcore-verify** if you are claiming the behavior.

A breaking schema change bumps `schema_version` and calls `assert_schema_evolution`. Catalog size and when to hide schemas are [docs/tools/discovery.md](../../docs/tools/discovery.md). Third-party servers go through [docs/tools/mcp-and-skills.md](../../docs/tools/mcp-and-skills.md) before `permit`.

## Do not

Do not copy package source into a template. Do not put resource ARNs or secrets in the schema examples or the eval fixture.

# Tool discovery

How many tools exist and how many schemas sit in the session prefix are different decisions. A Gateway catalog can be large while the prefix carries an index.

Concepts distilled from `tool-discovery` in [bojieli/ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/main/skills/tool-discovery). Credit: [attribution](../attribution/bojieli-ai-agent-book.md). Tool shape is [design.md](design.md). Prefix stability is [context budget](../runtime/context-budget.md).

## When the catalog grows

The source reports that once a catalog passes roughly a hundred tools, strong models start picking the wrong one, and a full dump of schemas dominates the prompt. Treat the bands below as design bands, not as measurements from this repo.

| Catalog size | What the session starts with |
| --- | --- |
| A dozen tools | Full schemas. `agentcore-tools` is here today (`put_record` and the demo registry). |
| Tens of tools | An index of `name` plus `description`. Load the full schema when the agent asks. |
| Hundreds | Retrieve a few candidates, then inject those schemas. |
| Hundreds to thousands | A discovery tool: the agent names the missing capability, a router returns a handful of schemas, or a skill index (see [MCP and skills](mcp-and-skills.md)). |

Group the index by source (search, read, parse, query) and say that grouping in the prompt, so the model picks a group before it picks a tool. Matching is hierarchical: server or target first, tool second. A low score at both layers returns "not found". A low-confidence guess is how the wrong tool gets called.

One-shot retrieval on the user's first sentence misses tools the task only needs later ("debug this file" becomes read, analyze, then execute). Active discovery exists for that gap. It is not implemented in `agentcore-tools`. Add it when a catalog actually crosses the bands above, with an eval that measures tool-choice accuracy and tokens in the prefix.

## Cache-safe loading

The static prefix is the system prompt plus the schemas present at session start. Keep that byte-stable.

- Append a newly loaded schema at the end of the trajectory, and leave it at that position on later turns.
- Do not insert it at the front, delete it, or reorder the set. The cache is invalid from the first changed token.
- The status line may list loaded names. It does not restate the schemas. See the state bar in [context budget](../runtime/context-budget.md).

Whether the transport is MCP and whether every schema is in the prefix are also separate. `agentcore-tools` can name an MCP server target. `to_configuration` fails for that target, so it is not synced to Gateway. The implemented target is Lambda.

## Skills as the light index

A skill directory of `name` plus `description`, with the body loaded on demand, is the same disclosure idea without an embedding index. Use it for procedures a person edits. Use a Gateway tool for a versioned, schema-checked side effect. The checklist for adding a skill in this repo is [pstack versus AgentCore skills](../skills/pstack-vs-agentcore.md).

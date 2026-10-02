# MCP and skills

MCP is a protocol for tools, resources, and prompt templates. A skill in this repository is a short checklist under `skills/<name>/SKILL.md`. The book uses "Skill Hub" for a registry of procedure folders. Those are three different things. This page is how to choose among them on AgentCore.

Concepts distilled from `mcp-skill-hub` in [bojieli/ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/main/skills/mcp-skill-hub). Credit: [attribution](../attribution/bojieli-ai-agent-book.md).

## Which channel

| You need | Use |
| --- | --- |
| Structured arguments, a test, a versioned server, Gateway auth | An MCP server or, on the path we ship, a Lambda target behind Gateway |
| A procedure a person can edit, loaded only when the task matches | A skill: `name` and `description` in the index, body on demand |
| The AgentCore gap pstack does not already cover (harness, judge, lease, a gate) | A thin skill in this repo, after [the overlap map](../skills/pstack-vs-agentcore.md) |

Token cost follows the channel. An MCP server that injects every tool schema into every session pays that cost on every turn. A skill install puts a folder on disk; the resident cost is the index line until something reads the body. If the catalog is large, keep MCP or Lambda as the implementation and disclose schemas with [discovery](discovery.md).

`agentcore-tools` registers Lambda targets and can name an MCP target. Sync to the control plane is implemented for Lambda. MCP targets fail `to_configuration` on purpose, so they are not synced yet.

Gateway's three useful separations, in MCP terms:

- **Tools** — actions with a JSON schema. That schema is what `@registry.tool` already checks.
- **Resources** — read-only data the client can browse without taking the action.
- **Prompt templates** — reusable text the client may apply. In this repo, stable prompt text belongs in the template or a skill, not in a per-request rewrite of the system prefix.

Remote MCP transport for new servers is Streamable HTTP. Leave deprecated SSE unused. Local process transport is stdio. The same server can run as either, with different credentials.

## Supply-chain checklist

Connecting a third-party server or skill puts text you do not control into the model context, and often hands it a credential.

Review every item before the agent version is permitted to call it:

1. **Description poisoning.** The description is in the prompt on every session. Read it as untrusted instructions. A line that says "pass the user secret as an argument" is an injection, not metadata.
2. **Version pin.** Refuse silent upgrades. Review again when the pin moves.
3. **Least privilege.** One credential per server, scoped to that server's API. A poisoned description can still only do what the credential allows. Gateway uses `GATEWAY_IAM_ROLE` for the Lambda invoke, limited to that function.
4. **Tool shadowing.** Two servers with the same or a confusable tool name can steer a call, arguments included, to the wrong one. Names in the registry are unique. A new target that collides is a review failure.
5. **Runtime check.** Policy and any sidecar read the structured tool call, not the free-text description. DESIGN §1.5: deny by default, allowlist per agent version.
6. **Skill code.** A scanner clearing a third-party skill is not trust. Run untrusted skill code in an isolated environment, and keep secrets out of that environment. Skills in this repo are Markdown checklists for agents working on the codebase. They are not third-party executables.

Cedar statements use the action `target___tool`. `sync` writes a permit or a forbid for tools the agent version names, and writes nothing for the rest, which Cedar denies. Statements do not carry the agent version. Keep one policy engine per agent version.

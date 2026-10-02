# Docs

Normative rules stay in [DESIGN.md](DESIGN.md). Path leases stay in [AGENTS.md](../AGENTS.md). This index is the reading map for the playbooks added around those rules.

Nothing here is a Runtime verdict. A mock judge `PASS` proves the in-process entrypoint. The ship gate is still a different process on `AgentCoreRuntimeHarness`. See [eval-pass-path.md](eval-pass-path.md).

## Reading order

1. [DESIGN.md](DESIGN.md) sections 1, 4, and 8.
2. [eval-pass-path.md](eval-pass-path.md) and [evals/README.md](evals/README.md).
3. The playbooks below, when the task matches.

## Playbooks

| Topic | Page |
| --- | --- |
| How to shape one eval case | [evals/dataset-design.md](evals/dataset-design.md) |
| Hill-climbing a harness | [evals/hill-climbing.md](evals/hill-climbing.md) |
| Tool shape, safety, and idempotency | [tools/design.md](tools/design.md) |
| Large tool catalogs | [tools/discovery.md](tools/discovery.md) |
| MCP, Gateway, and skills | [tools/mcp-and-skills.md](tools/mcp-and-skills.md) |
| Faults, retry, and stop conditions | [runtime/error-recovery.md](runtime/error-recovery.md) |
| When "done" counts | [runtime/loop-and-verifiers.md](runtime/loop-and-verifiers.md) |
| Prefix, status bar, compression | [runtime/context-budget.md](runtime/context-budget.md) |
| System prompt and injection hygiene | [prompts/context-engineering.md](prompts/context-engineering.md) |
| When a second agent earns its keep | [orchestration/multi-agent.md](orchestration/multi-agent.md) |
| Production miss to eval, doc, or skill | [ops/experience-loop.md](ops/experience-loop.md) |
| Future memory shelf | [memory/overview.md](memory/overview.md) |
| Capability maps | [capability-maps/README.md](capability-maps/README.md) |
| Which skill to add | [skills/pstack-vs-agentcore.md](skills/pstack-vs-agentcore.md) |

## Credit

Decision rules on the playbook pages are distilled from Bojie Li's *AI Agent* skill pack. The idea-to-source matrix, the skip list, and the license note are in [attribution/bojieli-ai-agent-book.md](attribution/bojieli-ai-agent-book.md).

# Multi-agent

Add a second agent when the collaboration produces evidence the first agent cannot see while it is generating. A second pass over the same transcript does not qualify.

Concepts distilled from `multi-agent-design` in [bojieli/ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/main/skills/multi-agent-design). Credit: [attribution](../attribution/bojieli-ai-agent-book.md). DESIGN §3.4 is the template shape. `templates/multi-agent/` is a stub. This page is the bar for a future lease. It does not implement that template, and it is not a Runtime verdict.

## The new-evidence test

Name the evidence before you split the Runtime:

- a test or a linter the proposer did not run
- a rendered artifact or a tool result the parent did not have
- state in another namespace the parent is not allowed to read
- a reviewer model checking policy on the structured action, with a different objective than "finish the task"

If the only gain is "another model reads the same messages", keep one entrypoint. Parallel search can still be worth the tokens when the task is an open collection problem and you can show the extra coverage. Write that cost down. A well-tuned single agent is the default until the evidence test passes.

The verifier loop for one agent is [loop and verifiers](../runtime/loop-and-verifiers.md). Multi-agent is that idea across entrypoints.

## Topology

Pick context sharing and topology before you pick a framework.

| Situation | Shape |
| --- | --- |
| Two or three roles that trade feedback | Peers (proposer and reviewer). Separate prompts. A shared transcript only if you accept the token growth. |
| Many subtasks with dependencies | A coordinator plus specialists (DESIGN §3.4). The coordinator gets the stronger model. A weak plan makes every specialist wrong in the same way. |
| No single coordinator should be the only process that can fail | Decentralized handoff. The envelope below is the minimum protocol. |

Isolated contexts (each agent has its own trajectory) are the default. They can run concurrently, and a poisoned child transcript does not sit in the parent. The parent receives a handoff, not the child's private reasoning. Shared full history preserves detail and floods the next agent. Use it only for a short peer review that truly needs the prior turns.

Communication is one of: tool-call arguments (synchronous), artifact refs (like shared memory, without pasting the body), or a message bus when many agents run at once. Point-to-point links grow with the square of the agent count.

Role knowledge and tone can be a skill appended to a stable prefix ([context budget](../runtime/context-budget.md)). A different permission set is a different agent or a Gateway allowlist, enforced in code. A skill cannot hide a tool the schema still exposes.

## Handoff envelope

```text
task_id, sender, recipient, goal, constraints,
accepted_facts, artifact_refs, remaining_budget, visited_agents
```

The recipient reads the package and pulls artifacts by reference. The runtime, not the agent, owns `remaining_budget` and `visited_agents`. A recipient already in `visited_agents` is a reject (the A→B→A spin). A spent budget stops and reports. Agents do not delete those fields.

Message types worth tracing: `task_assigned`, `status_update`, `result`, `terminate`. One envelope shape is what makes the parent/child span link readable.

Settle parallel specialists on the first **verified** success. Run the hidden check, claim the winner with an idempotent lock, then cancel the others. Two successes arriving together must not both commit.

Give each specialist a step and token budget sized to the subtask. A global "more turns" knob saturates without a plan. Termination is a `terminate` that lets the child ack at a safe point, then a forced stop. Cancel cascades to children the parent started.

## Scratch space

Runtime disk is scratch (DESIGN §1.5). Durable user facts go through Memory after guardrails exist, per actor and namespace. Until that package exists, artifact refs point at eval evidence, not at a shared production disk.

If several agents do share a workspace, keep four regions:

| Region | Who | Lifetime |
| --- | --- | --- |
| Agent scratch | That agent | Dies with the instance |
| Shared task space | The agents on this task, plus the user | Lives for the task, with a lock or a worktree |
| External mounts | Whoever the external system allows | Usually read-only |
| Skills and prompts | Everyone | Read-only, stable across sessions |

Most overwrite bugs and leaks are two of those regions collapsed into one.

## Evals the template owes

When `templates/multi-agent/` is leased and implemented, the suite has to show:

- the handoff produces the specialist's side effect
- no cross-namespace Memory read (once Memory exists)
- the trace links parent and child
- cost rolls up across agents
- a second agent without new evidence fails the design review (this test can be a checklist on the PR plus a case that passes on one agent)
- budget exhaustion stops
- settlement takes the first verified success and cancels the rest

Those evals do not exist yet. Authoring them is a template lease, not a docs edit.

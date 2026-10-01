# agentcore-memory

Stub for lane E. Not implemented.

Owns short-term events and long-term records, `actorId` / namespace isolation, and the guardrail check before write (DESIGN §2.3). Stacks on lane A and lane D. Do not implement in parallel with guardrails unless the guard interface is already on the default branch with a judge PASS.

Open decision (DESIGN §7): Memory connector via Gateway for all writes, or the Memory SDK for short-term only. Do not pick that inside a template.

Lease path: `packages/agentcore-memory/`.

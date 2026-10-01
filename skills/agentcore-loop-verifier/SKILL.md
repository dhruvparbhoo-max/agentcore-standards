---
name: agentcore-loop-verifier
description: >
  Treat an agent "done" claim as unverified until an independent check reads
  Runtime evidence. Use when a loop, a tool sequence, or a template reports
  the task complete. Covers premature completion, budgets, and a reviewer
  that cannot edit the assert.
---

# Verify the loop, not the claim

Read [docs/runtime/loop-and-verifiers.md](../../docs/runtime/loop-and-verifiers.md). Proving a package change on the harness is **agentcore-verify**. A different process shipping it is **agentcore-judge**.

## When

An entrypoint, a tool sequence, or a template can stop and say the task is finished.

## Steps

1. Name the observable (status, balance, row count, trajectory, span). The reply text is not the observable.
2. Add a premature-completion case: the transcript says complete, the world does not. The HITL pack's unpaid payment is the existing shape. Assert the world, and `result_excludes` when a success phrase is forbidden.
3. Point the reviewer at evidence from `invoke` and `capture_traces` (or a policy decision). A second reading of the proposer's explanation is not evidence.
4. Keep the reviewer from editing the assertion, `write_evidence`, and the publish bar.
5. Put a turn cap and a session budget on the loop. Spent budget without a pass is `FAIL` or an escalation.
6. If more than one worker can finish the task, settle on the first verified success, claim it idempotently, and cancel the rest.
7. Hand a ship claim to **agentcore-verify**, then **agentcore-judge**.

Fault classes and retry caps are [docs/runtime/error-recovery.md](../../docs/runtime/error-recovery.md). A second agent still has to pass the new-evidence test in [docs/orchestration/multi-agent.md](../../docs/orchestration/multi-agent.md).

## Do not

Do not accept "the model said done" as the verdict. Do not let a skipped Runtime test (`SKIPPED`) count as `PASS`.

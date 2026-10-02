---
name: agentcore-experience-to-gate
description: >
  Turn a repeated AgentCore production miss into a failing eval, then a doc
  or skill. Use when the same failure shows up again. Weight updates, DPO
  pairs, and reward functions are out of scope.
---

# From a miss to a gate

Run **agentcore-encode-miss** for the red-then-fix order. This skill chooses the artifact and stops the training path. The writeup is [docs/ops/experience-loop.md](../../docs/ops/experience-loop.md).

## When

The same miss has shown up in a trace, a dogfood report, or a correction, and someone is about to "remember it next time" or fine-tune it away.

## Steps

1. Keep the trace immutable. Attribute the first bad step: outcome (environment), then process (policy), then quality (rubric) only if the first two already exist.
2. Write the failure label, the evidence location (turn, tool, span), and whether the case is success, partial, or fail. Thin evidence stays out of the regression set.
3. Add the failing eval or extend `scripts/check_boundaries.py` before the product fix. Confirm the gate is red.
4. Fix on a PR. Confirm the gate is green, and the cases that already passed still pass.
5. If a judgment remains that no assert can hold, add a short doc or a thin skill. Read [docs/skills/pstack-vs-agentcore.md](../../docs/skills/pstack-vs-agentcore.md) first. A skill as the only control leaves the miss open.
6. For a behavior you will call done, continue with **agentcore-verify**.

## Do not

Do not update weights, build DPO pairs, or design an RL reward in this repo. Do not edit the verifier, the boundary script, or the evidence writer to make the miss pass. Do not let the running agent overwrite its own prompt or release. Online turns only append evidence.

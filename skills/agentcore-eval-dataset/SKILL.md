---
name: agentcore-eval-dataset
description: >
  Author or review one AgentCore eval case. Use when adding a scenario to
  the eval pack or a template suite. Covers the four-part task, deterministic
  checks, anti-cheat, and promoting a production miss to a regression case.
---

# Author an eval case

Read [docs/evals/dataset-design.md](../../docs/evals/dataset-design.md) and the field table in [docs/evals/README.md](../../docs/evals/README.md). This skill is the checklist for one case. The ship gate is still **agentcore-judge**.

## When

You are adding or changing a scenario, a guardrail fixture, a groundedness case, or a HITL case.

## Steps

1. Write the four parts: ticket (`turns[].input`), caller behavior if a person is simulated, initial state (books, allowlist, `now`), and success criteria a machine can re-check.
2. Assert end state, required tool names, and any fact the user must be told (`expected_response`, `expected_trajectory`, `metadata.outcomes`, `result_excludes`). Include the thing that must stay true (a second invoke, an untouched balance, a denied tool that writes nothing).
3. Do the task once by hand. Name the cheapest path that would pass without the work, and make the assert stop it.
4. Keep identifiers fictional. Parameterize them if the case is public and a hosted model could memorize the answer. A canary belongs in the task text only to detect leakage, never as a secret or a resource ARN.
5. Put the case in `packages/agentcore-eval` or the template suite that owns the behavior. Unknown JSON keys must fail the loader.
6. Run the offline suite and read the evidence file. For a behavior you are about to call done, continue with **agentcore-verify**.

A production miss follows **agentcore-encode-miss**: the new case fails on the bad trace before the fix. Tag a climb case `regression` only after that fix is in. Climb tags are in [docs/evals/hill-climbing.md](../../docs/evals/hill-climbing.md).

## Do not

Do not treat a public benchmark score as a product decision. Do not mark the case done from a green unit test. An offline `PASS` is not an `AgentCoreRuntimeHarness` verdict.

---
name: agentcore-encode-miss
description: >
  Turn a repeated AgentCore miss into a failing eval or CI gate before the
  fix. Use after principle-encode-lessons-in-structure. Covers a skipped
  Runtime check, an invented root cause, a cross-lease edit, a secret in a
  fixture, or a tool with no double-invoke coverage.
---

# Encode a miss as a gate

Run **principle-encode-lessons-in-structure** first and pick the strongest mechanism that can express the rule. On this repo that mechanism is a failing eval or a CI gate. Add a skill only after the gate exists, and only for judgment the gate cannot check.

## When

The same miss has happened again, or DESIGN §1.3 applies.

## Steps

1. Reproduce the miss once. Keep the failing command output.
2. Add the red gate before the product fix.
   - Behavior: an eval whose assertion fails on the bad behavior, under `templates/<name>/evals/` or that package's suite.
   - Boundary, copied package source, `experiments/` import, resource ARN, or private-key marker: extend `scripts/check_boundaries.py`, which CI already runs.
3. Run the gate. Confirm it fails on the reproduction.
4. Fix the code.
5. Run the gate again and confirm it passes. For a behavior change, continue with **agentcore-verify**.
6. If the observable or the drive path changed, update the capability map (`agentcore-capability-map`).

A comment, a style note, or a new skill as the only control leaves the miss open.

## Do not

**tdd** is the right path for a cheap local regression someone asked for. It does not replace the Runtime eval on a ship claim.

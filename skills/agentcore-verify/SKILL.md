---
name: agentcore-verify
description: >
  Prove an AgentCore behavior change on RuntimeHarness and keep the evidence
  JSON. Use after principle-prove-it-works, before calling a package or
  template change done. Use when the claim is a turn, span, log, cost
  attribute, or tool side effect.
---

# Verify on RuntimeHarness

Run **principle-prove-it-works** first. This skill is the surface that principle checks on this repo.

`RuntimeHarness` is the eval client: `start`, `invoke`, `capture_traces`, `tear_down`. `InMemoryRuntimeHarness` calls the entrypoint in-process. `AgentCoreRuntimeHarness` calls `InvokeAgentRuntime`. `BedrockAgentCoreApp` is the hosted process, not the harness.

## When

A package or template behavior changed, an eval changed, or someone is about to call that behavior done.

## Steps

1. Name the eval and the observable. The lane A eval is `minimal-agent.golden-turn` in `templates/minimal-agent/evals/golden_turn.py`.
2. Run the in-process harness and read the evidence file it writes. `run_eval` always calls `capture_traces` and `tear_down`, including when the assertion fails.

```bash
uv run pytest templates/minimal-agent/tests/test_golden_eval.py -m "not runtime"
```

For a suite added with the change, call `run_suite` with that template's harness and an `evidence_dir`. `evidence/` is gitignored. The evidence JSON includes spans, logs, status, and failures. It must match the observable. `write_evidence` redacts a resource ARN and records `FAIL`.

3. Put an author draft in the PR: eval name, evidence path, which harness ran, status (`PASS`, `PASS+NOTES`, or `FAIL`), and what this run did not prove.
4. Hand the ship check to **agentcore-judge**. A different process re-runs the eval. That draft is not the ship verdict.

Local commands that stay on this side of the ship gate:

```bash
uv sync --all-packages
uv run ruff check .
uv run mypy
uv run pytest -m "not runtime"
uv run python scripts/check_boundaries.py
```

`uv run pytest -m runtime` needs `AWS_REGION`, `AGENTCORE_RUNTIME_ARN`, and `AGENTCORE_SPAN_LOG_GROUP` in the environment. Names are in `.env.example`. Values stay out of git. The `runtime-evals` workflow runs the runtime judge. Missing settings write `SKIPPED` and the job fails. That failure is not a PASS, and a green skip is not the gate.

## Do not

Do not run **create-verification-skill**. This repo has no UI to drive. Capability maps live in `docs/capability-maps/`.

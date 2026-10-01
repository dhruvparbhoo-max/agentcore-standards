# Evals

How this repo runs and improves evals. A ship gate is still DESIGN §1.1 and §4.2: a different process from the author re-runs AgentCore Runtime and records `PASS`, `PASS+NOTES`, or `FAIL`. CI green is not that verdict.

## Hill-climbing

[hill-climbing.md](hill-climbing.md) is the operating rhythm for a harness change after Runtime and tracing are hooked up.

Source and tag cases, split optimization from holdout, record a baseline, make one harness change, check regressions, human review, then promote or prune. Production traces feed the next cases. The page states that rhythm in plain language and then maps it onto `RuntimeHarness`, dataset tags, and evidence files.

```bash
uv run python -m agentcore_eval.hillclimb steps
```

`compare` diffs two evidence directories. It does not call Runtime. A clear diff is not a ship verdict, and this repo has not recorded a production climb.

## What you can run today

The golden eval is `minimal-agent.golden-turn`. Details and the real Runtime command: [templates/minimal-agent/README.md](../../templates/minimal-agent/README.md).

```bash
uv run pytest templates/minimal-agent/tests/test_golden_eval.py -m "not runtime"
uv run pytest -m runtime
```

The second command calls Runtime only when `AWS_ACCESS_KEY_ID`, `AWS_REGION`, `AGENTCORE_RUNTIME_ARN`, and `AGENTCORE_SPAN_LOG_GROUP` are set. Otherwise it skips. A skip is not a `PASS`.

Harness API: [packages/agentcore-eval/README.md](../../packages/agentcore-eval/README.md).

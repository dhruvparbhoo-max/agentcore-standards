# minimal-agent

Thinnest AgentCore agent. An application, not a PyPI library. Version 0.1.0, matching `AGENT_VERSION`.

Depends explicitly on `agentcore-tracing`, `agentcore-eval`, and `bedrock-agentcore` ≥ 1.24. It does not vendor those packages.

## What it does

`invoke` is the `@app.entrypoint` on `BedrockAgentCoreApp`. It rejects a `prompt` that is not a non-empty string, opens `agent.turn` and a child `model.invoke`, records cost attributes, and emits one JSON log. The completion is `pong:` plus the stripped prompt. There are no tools and no Memory.

`MinimalAgentHarness` implements `RuntimeHarness` by delegating:

- default: `InMemoryRuntimeHarness(handle_turn)` so evals call this entrypoint in-process
- `MinimalAgentHarness.for_agentcore_runtime()`: `InvokeAgentRuntime` against the deployed service

## Golden eval

`evals/golden_turn.py` exports `EVAL` named `minimal-agent.golden-turn`.

Observable: two turns on one session return `pong:ping` and `pong:again`; each `agent.turn` has a hashed session id and `cost.source=length-heuristic` at zero USD; `model.invoke` is a child of that turn; logs carry the hashed `runtimeSessionId`, `actorId`, `agentVersion`, `requestId`, and `latencyMs`. The zero-USD figure is the deterministic pong path, not model-reported usage.

Judge process (this is the PASS path, not the author pytest):

```bash
PYTHONPATH=templates/minimal-agent/src uv run python -m minimal_agent.judge --evidence-dir evidence/judge
```

`evidence/judge/verdict.json` is the roll-up. `evidence/judge/minimal-agent.golden-turn.json` is the spans and logs. `--harness runtime` is the real AgentCore Runtime path. Missing settings write `SKIPPED` and exit 1. Details: [docs/eval-pass-path.md](../../docs/eval-pass-path.md).

Author unit check:

```bash
uv run pytest templates/minimal-agent/tests/test_golden_eval.py -m "not runtime"
```

## Point the same eval at AgentCore Runtime

1. Deploy this entrypoint (`PYTHONPATH=templates/minimal-agent/src uv run python -m minimal_agent` is the local server on port 8080; Runtime hosts that same app).
2. Export `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `AGENTCORE_RUNTIME_ARN`, and `AGENTCORE_SPAN_LOG_GROUP`. Optional: `AGENTCORE_RUNTIME_QUALIFIER`.
3. Run `uv run pytest -m runtime`.

The runtime test is skipped when any of those values is missing. Names are listed in the repo `.env.example`. Values stay out of git.

A green in-memory run is the local check. It is not the independent Runtime verdict required to merge (DESIGN §4.2, §8).

Capability map: [docs/capability-maps/minimal-agent.md](../../docs/capability-maps/minimal-agent.md).

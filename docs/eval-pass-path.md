# Independent PASS path

A ship verdict is `PASS` or `PASS+NOTES` from a **separate process** that re-runs the eval. The author's pytest run is not that verdict. CI green is not that verdict. This page is how to produce one. The rule lives in [the library design](design/library.md).

The judge calls `RuntimeHarness` in this order:

1. `start(actor_id, agent_version)` binds a session.
2. `invoke(session, payload)` sends each turn. The golden eval sends two.
3. `capture_traces(session)` collects spans and structured logs. The eval assertion reads them, and the runner reads them again after the assertion.
4. `tear_down(session)` ends the session. The runner always does this, including when the assertion fails.

`verdict.json` records that call list under `evals[].lifecycle`.

## Where evidence lands

Each judge process writes one directory (default `evidence/judge/`, gitignored):

| File | Contents |
| --- | --- |
| `verdict.json` | Roll-up status, harness name, lifecycle, failures, notes |
| `<eval-name>.json` | Spans, structured logs, and the per-eval status |

`evidence/judge/` is the directory CI uploads. A local run can pass `--evidence-dir` to put it somewhere else. A bundle that contains a resource ARN is redacted and the verdict is rewritten to `FAIL`. The judge does not raise and leave the file unwritten.

Exit codes: `0` for `PASS` and `PASS+NOTES`. `1` for `FAIL` and for `SKIPPED`. `SKIPPED` means the real Runtime settings were missing. The JSON says `SKIPPED`. The process still exits 1, because a missing surface is not a ship verdict. `--allow-runtime-skip` exits 0 for a local dry run. The Runtime workflow does not pass that flag.

## Mock / bootstrap path (no AWS credentials)

This path calls the minimal-agent entrypoint in-process through `InMemoryRuntimeHarness`. It does not call `InvokeAgentRuntime`.

From the repo root:

```bash
uv sync --all-packages
PYTHONPATH=patterns/minimal-agent/src uv run python -m minimal_agent.judge --evidence-dir evidence/judge
```

Expect:

```text
status: PASS
harness: memory
verdict: evidence/judge/verdict.json
eval: minimal-agent.golden-turn PASS evidence/judge/minimal-agent.golden-turn.json
```

What this proves: two turns on one session return `pong:ping` and `pong:again`; `agent.turn` has a hashed session id and `cost.source=length-heuristic` at zero USD (the deterministic pong path, not model-reported usage); `model.invoke` is a child span; the JSON log has the hashed session id, actor, version, and request id; the process itself ran `start`, `invoke`, `capture_traces`, and `tear_down`.

What this does not prove: a deployed AgentCore Runtime microVM, CloudWatch spans, or IAM. Do not auto-merge on this result alone.

CI runs the same command in `.github/workflows/ci.yml` and uploads `evidence/judge/` as the artifact `minimal-agent-judge-evidence`.

## Real AgentCore Runtime path

Same eval, same judge process, harness `runtime`. That harness calls `InvokeAgentRuntime` with the actor on `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id`, collects ADOT spans (`attributes.session.id` is the raw session id) and `agentcore.turn` logs (`runtimeSessionId` is the hash), then `tear_down` calls `StopRuntimeSession`. It does not call the Evaluate API. `OnDemandEvaluationDatasetRunner` stays a later adapter. The golden cost check on this path is still the length heuristic at zero USD. It is not a billing proof. See [the library design](design/library.md).

```bash
PYTHONPATH=patterns/minimal-agent/src uv run python -m minimal_agent.judge \
  --harness runtime \
  --evidence-dir evidence/judge
```

Required environment (names only; values stay out of git — see `.env.example`):

| Name | Role |
| --- | --- |
| `AWS_REGION` | Region of the dev account. Required. |
| `AGENTCORE_RUNTIME_ARN` | Deployed runtime identifier. Required. Not committed. |
| `AGENTCORE_SPAN_LOG_GROUP` | CloudWatch log group name for span collection. Required. Not an ARN in git. |
| `AGENTCORE_APP_LOG_GROUP` | Optional application-log group for turn logs. Defaults to the span log group. |
| `AWS_ACCESS_KEY_ID` | Optional. Required only when `AWS_SECRET_ACCESS_KEY` is set, and the reverse. A role needs neither. |
| `AGENTCORE_RUNTIME_QUALIFIER` | Optional endpoint qualifier. |

`from_env` and `missing_runtime_settings` use this same set.

IAM in the dev account, scoped to that runtime and those log groups:

- `bedrock-agentcore:InvokeAgentRuntime`
- `bedrock-agentcore:StopRuntimeSession`
- `logs:StartQuery`
- `logs:GetQueryResults`

Isolate with agent version, namespace, and IAM path. Do not use a second account. See [the library design](design/library.md).

When any required name is unset, the command prints `status: SKIPPED`, writes `verdict.json` with `"status": "SKIPPED"` and `missing_settings`, and exits 1. It does not write a golden-eval evidence file and it does not print `PASS`. `.github/workflows/runtime-evals.yml` runs this command and fails closed. A red check without those secrets is the gate, not a skipped success.

A real Runtime PASS is `status: PASS` or `status: PASS+NOTES` from `--harness runtime`, with `minimal-agent.golden-turn.json` full of service spans. That file is the evidence a later judge retains. This repository does not contain that PASS.

## Who re-runs

The author and the judge are different processes. The judge does not read the author's chat. It only needs the repo and, for the real path, the environment above.

```bash
PYTHONPATH=patterns/minimal-agent/src uv run python -m minimal_agent.judge --evidence-dir evidence/judge
```

A second machine or a second cloud agent runs that command again. Matching `PASS` / `PASS+NOTES` plus the evidence files is the independent verdict. `FAIL` or a missing evidence file blocks merge. `SKIPPED` blocks merge too: the real surface was not exercised.

Generic form, if the harness factory is not the minimal agent:

```bash
uv run python -m agentcore_eval.judge \
  --suite patterns/minimal-agent/evals \
  --agent-version 0.1.0 \
  --harness-name memory \
  --harness-factory minimal_agent.harness:MinimalAgentHarness \
  --evidence-dir evidence/judge
```

`PYTHONPATH` must include `patterns/minimal-agent/src` for that factory import. Patterns stay applications; this command does not install them as libraries.

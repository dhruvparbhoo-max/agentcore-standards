# agentcore-eval

Eval harness at the AgentCore Runtime boundary (DESIGN §2.6). Version 0.1.0.

```text
start(actor_id, agent_version, session_id?) -> SessionHandle
invoke(session, payload) -> InvokeResult
capture_traces(session) -> TraceBundle
tear_down(session)
```

`run_eval` / `run_suite` return `PASS`, `PASS+NOTES`, or `FAIL` and write an evidence JSON file. They always capture traces and tear the session down, including on failure.

`python -m agentcore_eval.judge` is the separate judge process. It records the lifecycle (`start`, `invoke`, `capture_traces`, `tear_down`) into `verdict.json`. See [docs/eval-pass-path.md](../../docs/eval-pass-path.md).

| Type | Role |
| --- | --- |
| `InMemoryRuntimeHarness` | Calls a Python entrypoint in-process. Default golden path. |
| `AgentCoreRuntimeHarness` | Calls `InvokeAgentRuntime`. Built with `from_env()`. |
| `HarnessAgentInvoker` | Adapts a harness to the `payload` + `session_id` turn shape used by `OnDemandEvaluationDatasetRunner`. |
| `load_on_demand_runner` | Imports that SDK runner. Lane A does not call `run`. |

`OnDemandEvaluationDatasetRunner` is the later service-side path (invoke, wait for CloudWatch, call Evaluate). Wire it in the runtime-evals workflow when a dataset and span log group exist. Do not confuse it with `RuntimeHarness`.

Evidence files refuse to persist a resource ARN.

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
| `HarnessAgentInvoker` | Adapts a harness to the `payload` + `session_id` turn shape used by `OnDemandEvaluationDatasetRunner`. A string payload becomes `{"prompt": ...}`. |
| `load_on_demand_runner` | Imports that SDK runner. |
| `OnDemandEvaluatorsAdapter` | Optional call to `OnDemandEvaluationDatasetRunner.run`. Returns the SDK result, not a `Verdict`. |

`OnDemandEvaluationDatasetRunner` is the service-side path (invoke, wait for CloudWatch, call Evaluate). It does not replace `run_eval` / `run_suite`. The eval pack — business goldens, guardrail fixtures, groundedness, and HITL — is documented in [docs/evals/README.md](../../docs/evals/README.md). Offline runs use `business_harness()` from `agentcore_eval.stub_agent` and `pack_suite_dir()`. Those stand-ins are not exported from the package root.

`InMemoryRuntimeHarness` is the in-process eval client in `agentcore_eval.in_memory`. It is not the product memory package.

Evidence that contains a resource ARN is redacted and recorded as `FAIL`.

A runtime judge with missing settings writes `SKIPPED` and exits 1. `PASS` and `PASS+NOTES` are the only exit-0 statuses.

# Runbooks

Every pattern names a runbook in `pattern.yaml` (`runbook_url`) and an alert route (`alert_route`). `agentcore-kit check-kit` fails when a relative `runbook_url` does not exist. A pattern with its own failure modes adds `patterns/<name>/docs/runbook.md` and points `runbook_url` at it. Otherwise it uses this page.

The "check first" hints follow the alarm descriptions in aws-samples/sample-agentcore-enterprise-platform `stacks/observability_stack.py` (Apache-2.0, see [NOTICE](../../NOTICE)). The alarms themselves arrive with the front door (step 4).

## Any agent runtime

| Symptom | Check first | Then |
| --- | --- | --- |
| SystemErrors on `InvokeAgentRuntime` for two periods | The runtime's log group `/aws/bedrock-agentcore/runtimes/<runtime>-<endpoint>`. Filter on the hashed `session_id` from the failing call. | If the errors started with a release, point the endpoint back at the previous version (rollback below). |
| Throttles on `InvokeAgentRuntime` | Concurrent sessions against the AgentCore Runtime quota. | Raise the quota, or lower the front door's per-user rate limit. |
| p99 latency above 30 s for 15 minutes | The slow trace in CloudWatch Transaction Search. Look for a tool span or a model retry loop. | A tool at fault: turn it off with a Cedar forbid. A model at fault: check Bedrock throttles and the fallback model. |
| `/ping` reports `HealthyBusy` for a long time | Background work started with `run_in_background` that never completed. | Stop the session (`StopRuntimeSession`); the checkpoint lets the next session resume. |
| A reply leaks something it should not | The `release_id` on the trace. | Kill switch for the agent (front door, step 4), then roll back. |

## Rollback

Versions are immutable. A named endpoint stays on the version it points at. Rollback points the endpoint back at the previous version, with no new image build: `update_agent_runtime_endpoint(agentRuntimeId=..., endpointName=..., agentRuntimeVersion=<previous>)`. `ListAgentRuntimeVersions` finds the previous one. Then run `agentcore-kit verify` against that version.

## Logs

Logs are JSON lines carrying `session_id` (hashed) and `user_id`. Prompt and reply text are not logged. Email addresses and IP addresses are masked by the log group's data protection policy. Unmasking needs the `logs:Unmask` policy scoped to that log group.

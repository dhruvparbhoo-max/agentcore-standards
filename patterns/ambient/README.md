# Ambient

An event becomes a job, the job runs an agent, and a risky action waits for a person. The trigger writes a job row with a conditional put on source plus event id. A duplicate delivery is a no-op. The worker calls the agent through the same session API the front door uses. It does not call AgentCore Runtime directly.

The wait for a person lives on the job row (`waiting_for_approval`), not in the microVM. The pause token is the same one as the human-approval pattern.

The agent acts as a **service** with a stored consent record (`consent_ref` on the event).

## Prerequisites

- Docker (Docker Desktop, Colima, or Rancher) or Finch on a Mac. `docker ps` (or `finch ps`) must succeed before a local run or a deploy.
- Python 3.12 and uv, or the repo's `.devcontainer`.
- For a deploy: AWS credentials, the AWS CDK, and the AgentCore CLI. `uv run agentcore-kit doctor patterns/ambient --env dev` checks them and changes nothing.

## Run it locally

```bash
docker ps
uv run pytest patterns/ambient
```

`make local` still fronts `patterns/_template`. This pattern's offline proof is the pytest job-store and golden tests. No AWS account is used.

## Deploy and tear down

```bash
make deploy PATTERN=ambient ENV=dev
make teardown PATTERN=ambient ENV=dev
```

No deploy from this repo has been run against a live AWS account. A live trigger Lambda and DynamoDB job table are not in this change; `JobStore` is the in-process stand-in.

## The kit

| Item | Where |
| --- | --- |
| 1. README with prerequisites | this file |
| 2. `pattern.yaml`, generated `agentcore/agentcore.json` | `pattern.yaml`, `agentcore/` |
| 3. Prompt files | `prompts/system.md` |
| 4. Cedar tool limits | `policies/tools.cedar` |
| 5. Approval on send, spend, delete, change | `approval.required_for`; wired tool is `change` |
| 6. Tracing with the release id | `build_agent` |
| 7. Unit and contract tests | `tests/`, `tests/e2e/` (marked `runtime`, skipped without credentials) |
| 8. Golden set | `eval/golden_set.json` |
| 9. Sample events | `events/invoice-pack.json`, `events/vendor-close.json` |
| 10. Untrusted-input tags, guardrails | event text is tagged as user/event input through `build_agent` |
| 11. Step, timeout, retry limits | `lifecycle` (idle 1800s, max 14400s because a job attempt is longer than chat) |
| 12. CDK deploy and teardown, ARM64 image | `infra/app.py`, `agent/Dockerfile` |

## Events

`trigger` is `event`. Each file is a sample queue event. The idempotency key is `source` plus `event_id`.

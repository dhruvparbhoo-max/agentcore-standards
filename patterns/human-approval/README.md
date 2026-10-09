# Human approval

Four ways to ask a person, one pause. Send, spend, delete, and change wait. This pattern wires `submit_change` (`action: change`). The other three action classes use the same `pause_for_human` token: bound to the tool, the argument hash, and the actor; the approver cannot be the actor; `consume` spends the token once.

The four asks (a hook, tool context, a Step Functions wait, and MCP elicitation) live in `human_approval/ask.py`. All four call `pause_for_human`. The agent uses the hook: the loop interrupts, `build_agent` opens the ticket. The other three are written so a later pattern can pick them without inventing a second token. None of them have been run against AWS.

## Prerequisites

- Docker (Docker Desktop, Colima, or Rancher) or Finch on a Mac. `docker ps` (or `finch ps`) must succeed before a local run or a deploy.
- Python 3.12 and uv, or the repo's `.devcontainer`.
- For a deploy: AWS credentials, the AWS CDK, and the AgentCore CLI. `uv run agentcore-kit doctor patterns/human-approval --env dev` checks them and changes nothing.

## Run it locally

```bash
docker ps
uv run pytest patterns/human-approval primitives/gateway-tools/submit_change
```

`make local` still fronts `patterns/_template`. This pattern's offline proof is the pytest golden score (pause) plus the resume unit test. No AWS account is used.

## Deploy and tear down

```bash
make deploy PATTERN=human-approval ENV=dev
make teardown PATTERN=human-approval ENV=dev
```

No deploy from this repo has been run against a live AWS account.

## The kit

| Item | Where |
| --- | --- |
| 1. README with prerequisites | this file |
| 2. `pattern.yaml`, generated `agentcore/agentcore.json` | `pattern.yaml`, `agentcore/` |
| 3. Prompt files | `prompts/system.md` |
| 4. Cedar tool limits | `policies/tools.cedar` (permits `submit_change` only) |
| 5. Approval on send, spend, delete, change | `approval.required_for`; the wired tool is `change` |
| 6. Tracing with the release id | `build_agent` |
| 7. Unit and contract tests | `tests/`, `tests/e2e/` (marked `runtime`, skipped without credentials) |
| 8. Golden set | `eval/golden_set.json` |
| 9. Sample events | `events/change.json` |
| 10. Untrusted-input tags, guardrails | `build_agent` |
| 11. Step, timeout, retry limits | `lifecycle` in `pattern.yaml` |
| 12. CDK deploy and teardown, ARM64 image | `infra/app.py`, `agent/Dockerfile` |

## Events

`trigger` is `none`, so `events/change.json` is a front door payload. The expected status is `paused`. An overnight wait belongs on a job row (the ambient pattern); this chat pattern's token lasts `approval.expire_s`.

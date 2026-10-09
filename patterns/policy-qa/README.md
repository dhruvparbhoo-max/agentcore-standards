# Policy Q&A

Company-policy questions. The agent retrieves through a **trusted wrapper** (`policy_qa.knowledge`) that filters by the tenant and role on the verified login, then cites the passage ids. When retrieve returns nothing, the reply is exactly `I couldn't find this in the policies`. There is no `search_policies` tool. The Gateway knowledge-base target is the live retrieve; locally the wrapper uses `agentcore_tools.Corpus`.

The fixture set is messy on purpose: two leave policies that disagree, a licence-refund note that shares the word "refund", and a second tenant so a wrong filter would leak.

## Prerequisites

- Docker (Docker Desktop, Colima, or Rancher) or Finch on a Mac. `docker ps` (or `finch ps`) must succeed before a local run or a deploy.
- Python 3.12 and uv, or the repo's `.devcontainer`.
- For a deploy: AWS credentials, the AWS CDK, and the AgentCore CLI. `uv run agentcore-kit doctor patterns/policy-qa --env dev` checks them and changes nothing.

## Run it locally

```bash
docker ps
uv run pytest patterns/policy-qa
```

`make local` still fronts `patterns/_template` on port 8080. This pattern's offline proof is the pytest golden score, not the compose stack. No AWS account is used.

## Deploy and tear down

```bash
make deploy PATTERN=policy-qa ENV=dev
make teardown PATTERN=policy-qa ENV=dev
```

`make deploy` refuses a production environment while `agentcore-kit production-check` reports a missing control (the guardrail service is still off). No deploy from this repo has been run against a live AWS account.

The actor id the front door forwards must be `{tenant}/{role}/{user}` so the wrapper can filter without asking the model.

## The kit

| Item | Where |
| --- | --- |
| 1. README with prerequisites | this file |
| 2. `pattern.yaml`, generated `agentcore/agentcore.json` | `pattern.yaml`, `agentcore/` |
| 3. Prompt files | `prompts/system.md` |
| 4. Cedar tool limits | `policies/tools.cedar` (permits none; retrieve is not a tool) |
| 5. Approval on send, spend, delete, change | empty; this pattern does not those actions |
| 6. Tracing with the release id | `build_agent` |
| 7. Unit and contract tests | `tests/`, `tests/e2e/` (marked `runtime`, skipped without credentials) |
| 8. Golden set | `eval/golden_set.json` (`source-backed`, `goal-success`, `eval.groundedness: 0.7`) |
| 9. Sample events | `events/leave.json`, `events/missing.json` |
| 10. Untrusted-input tags, guardrails | documents tagged `source="document"`; user text tagged `source="user"` |
| 11. Step, timeout, retry limits | `lifecycle` in `pattern.yaml` |
| 12. CDK deploy and teardown, ARM64 image | `infra/app.py`, `agent/Dockerfile` |

## Events

`trigger` is `none`, so the files under `events/` are front door payloads for a local post, not queue events.

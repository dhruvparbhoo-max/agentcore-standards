# Template pattern

Copy this folder to start a pattern: `cp -r patterns/_template patterns/<name>`, then change `name` in `pattern.yaml`, the package name in `agent/pyproject.toml`, and the paths in `agent/Dockerfile`. Run `uv run agentcore-kit generate patterns/<name>` and `uv run agentcore-kit check-kit patterns/<name>` until the check passes.

The template answers one chat turn with no tools. It shows the twelve kit items in their places.

## Prerequisites

- Docker (Docker Desktop, Colima, or Rancher) or Finch on a Mac. `docker ps` (or `finch ps`) must succeed before a local run or a deploy.
- Python 3.12 and uv, or the repo's `.devcontainer`, which has Python, uv, Node, the AWS CDK, and the AgentCore CLI.
- For a deploy: AWS credentials for the target account, the AWS CDK, and the AgentCore CLI (`npm install -g @aws/agentcore`). `uv run agentcore-kit doctor patterns/_template --env dev` checks all of them and changes nothing.

## Run it locally

```bash
docker ps
make local PATTERN=_template      # compose: agent (scripted model) + DynamoDB Local + LocalStack, then posts events/*.json
uv run pytest patterns/_template  # unit and contract tests; e2e tests skip without a deployed runtime
```

## Deploy and tear down

```bash
make deploy PATTERN=_template ENV=dev     # CDK foundation, ARM64 image to ECR, agentcore deploy
make teardown PATTERN=_template ENV=dev   # always run after a test deploy
```

`make deploy` refuses a production environment while `agentcore-kit production-check` reports a missing control. No deploy from this repo has been run against a live AWS account yet.

## The kit

| Item | Where |
| --- | --- |
| 1. README with prerequisites | this file |
| 2. `pattern.yaml`, generated `agentcore/agentcore.json` | `pattern.yaml`, `agentcore/` |
| 3. Prompt files | `prompts/system.md` |
| 4. Cedar tool limits | `policies/tools.cedar` |
| 5. Approval on send, spend, delete, change | `approval` in `pattern.yaml`; the template has no such tools |
| 6. Tracing with the release id | `build_agent` opens the turn span |
| 7. Unit and contract tests | `tests/`, `tests/e2e/` (marked `runtime`) |
| 8. Golden set | `eval/golden_set.json` |
| 9. Sample events | `events/hello.json` |
| 10. Untrusted-input tags, guardrails, secrets by name | `build_agent`; `config/environments/*.yaml` |
| 11. Step, timeout, retry limits | `lifecycle` in `pattern.yaml` |
| 12. CDK deploy and teardown, ARM64 image | `infra/app.py`, `agent/Dockerfile`, `Makefile` |

## Events

`trigger` is `none`, so `events/hello.json` is a front door payload for `make local`, not a queue event.

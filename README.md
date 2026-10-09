# agentcore-standards

Standards library for coding agents and humans building on [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html). This repository holds versioned Python primitives, runnable agent templates, and the eval harness those templates share. It is not a hosted platform.

The library design is [docs/design/library.md](docs/design/library.md). Path leases for parallel agents live in [AGENTS.md](AGENTS.md). Playbooks for eval cases, tools, recovery, and production misses are indexed in [docs/README.md](docs/README.md). Those pages restate selected rules from Bojie Li's *AI Agent* skill pack for AgentCore; the credit matrix is [docs/attribution/bojieli-ai-agent-book.md](docs/attribution/bojieli-ai-agent-book.md).

Lane A is the root of every later stack: `agentcore-tracing`, `agentcore-eval`, and `templates/minimal-agent`, with one golden eval. The shared shelf and `templates/agent-with-tools` are implemented offline. Neither is a live Runtime PASS. `agentcore-session` stays a stub.

## Layout

Shared libraries live under `primitives/<name>/`. Folder names are short. Python distribution names (`agentcore-tracing`) and import names (`agentcore_tracing`) are unchanged. `patterns/` holds self-contained deployable examples; `patterns/_template/` is the starter kit. `templates/` and `experiments/` stay where they are until later steps retire them.

```
primitives/tracing/             OTEL span names, hashed session id, cost attributes, JSON turn logs
primitives/eval/                RuntimeHarness, verdicts, suite runner, in-memory harness, Runtime client
primitives/session/             stub (lane B); actor headers are agentcore-identity
primitives/tools/               registry, Gateway Lambda targets, idempotency, compact, cite, catalog
primitives/guardrails/          input, output, and memory-write checks
primitives/memory/              short-term events and long-term records, after the guard
primitives/identity/            Runtime actor and session headers
primitives/approvals/           single-use approval tokens
primitives/context/             prompt assembly and the state bar
primitives/recovery/            retry budget, circuit breaker, in-flight cap
primitives/completion/          completion check; proposer is not the verifier
primitives/langchain/           LangChain create_agent over the tool registry, plus graph helpers
primitives/agent/               pattern.yaml, build_agent (create_agent | strands | harness), agentcore-kit CLI
primitives/gateway-tools/       one Gateway tool per folder, each its own image and registry listing
patterns/_template/             the 12-item starter kit; copy it to start a pattern
infra/                          CDK foundation construct and the secret rotation Lambda
docker/                         digest-pinned base images and the compose stand-ins
config/environments/            per-environment settings (no account ids)
templates/minimal-agent/        BedrockAgentCoreApp entrypoint plus a harness binding (an app, not a PyPI lib)
templates/agent-with-tools/     invoice desk; imports the shelf; offline judge; no live Runtime PASS
templates/multi-agent/          stub
templates/human-in-the-loop/    stub
experiments/                    messy drafts allowed; templates and primitives must not import them
docs/DESIGN.md                  team standards
docs/README.md                  index of playbooks (evals, tools, runtime, ops)
docs/capability-maps/           how to drive a template and what observable proves it
docs/evals/                     eval pack index, dataset design, hill-climbing
docs/skills/pstack-vs-agentcore.md   pstack skill to run, and the AgentCore skill if one exists
docs/attribution/               credit for distilled playbooks and copied reference code (see NOTICE)
skills/                         verify, judge, lease, encode-miss, capability map, eval-dataset, tool-register, loop-verifier, experience-to-gate
```

## Two different things named like a harness

| Name | What it is |
| --- | --- |
| `BedrockAgentCoreApp` | The server process AgentCore Runtime hosts. `@app.entrypoint` is `POST /invocations`. |
| `RuntimeHarness` | The eval client: `start`, `invoke`, `capture_traces`, `tear_down`. |
| `InMemoryRuntimeHarness` | Calls the entrypoint in-process and keeps its spans. Default for the golden eval. |
| `AgentCoreRuntimeHarness` | Calls the Runtime **service** (`InvokeAgentRuntime`) when environment credentials exist. |

Evals stay on `RuntimeHarness`. Replacing the hosted container later re-wraps the entrypoint. It does not rewrite the eval.

## Prerequisites

- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- Docker, or [Finch](https://runfinch.com) on a Mac. `docker ps` (or `finch ps`) must succeed before `make local`, `make build`, or a deploy. Every container target checks it first; use `DOCKER=finch` with Finch.
- For a deploy only: Node 22, the [AgentCore CLI](https://github.com/aws/agentcore-cli) (`npm install -g @aws/agentcore`), the AWS CDK CLI, and the AWS CLI. `make doctor ENV=dev` checks all of them read-only.

The `.devcontainer/` image carries every tool above at pinned versions. CI runs in that image.

## Install

```bash
uv sync --all-packages
make local        # compose stack: template agent, a Gateway tool, DynamoDB Local, LocalStack; posts events/*.json
```

The root project depends on `agentcore-tracing` and `agentcore-eval` explicitly. `templates/minimal-agent` is an application workspace member (`package = false`), and it declares those same packages itself. Do not copy package source into a template.

## Unit tests

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest -m "not runtime"
uv run python scripts/check_boundaries.py
```

`pytest` without the marker also skips the real Runtime test when credentials are absent. CI runs the commands above.

## Evals and the independent judge

The shared eval pack (business goldens, guardrail fixtures, groundedness, HITL, and the optional Evaluators adapter) is documented in [docs/evals/README.md](docs/evals/README.md). Offline, `run_suite` drives those cases through `InMemoryRuntimeHarness`. That pass is not a Runtime verdict.

The full PASS path is [docs/eval-pass-path.md](docs/eval-pass-path.md). Short version: a **separate process** re-runs `minimal-agent.golden-turn` through `start`, `invoke`, `capture_traces`, and `tear_down`, then writes evidence.

The template golden eval is `minimal-agent.golden-turn` in `templates/minimal-agent/evals/golden_turn.py`. It sends two turns on one session and checks the deterministic `pong:` completion, the `agent.turn` / `model.invoke` span tree, cost attributes, and structured logs.

Mock / bootstrap (no AWS credentials). This is runnable now:

```bash
PYTHONPATH=templates/minimal-agent/src uv run python -m minimal_agent.judge --evidence-dir evidence/judge
```

Evidence lands in `evidence/judge/verdict.json` and `evidence/judge/minimal-agent.golden-turn.json`. `status: PASS` here proves the in-process entrypoint. It does not prove AgentCore Runtime.

Real Runtime (same command, different harness). Missing settings write `status: SKIPPED` and exit 1. That is not a PASS:

```bash
PYTHONPATH=templates/minimal-agent/src uv run python -m minimal_agent.judge --harness runtime --evidence-dir evidence/judge
```

Set `AWS_REGION`, `AGENTCORE_RUNTIME_ARN`, and `AGENTCORE_SPAN_LOG_GROUP`. An access key and its secret are a pair; a role needs neither. The dev account is the eval account. IAM needs `bedrock-agentcore:InvokeAgentRuntime`, `bedrock-agentcore:StopRuntimeSession`, `logs:StartQuery`, and `logs:GetQueryResults`. Names are listed in `.env.example`. Do not commit values.

`.github/workflows/ci.yml` runs the mock judge and uploads `evidence/judge`. `.github/workflows/runtime-evals.yml` runs the runtime judge and fails when settings are absent. This repository does not contain a live Runtime PASS.

Author pytest is still useful, and it is not the ship verdict:

```bash
uv run pytest templates/minimal-agent/tests/test_golden_eval.py -m "not runtime"
uv run pytest -m runtime
```

Serve the entrypoint the way Runtime hosts it (port 8080):

```bash
PYTHONPATH=templates/minimal-agent/src uv run python -m minimal_agent
```

## Ownership

Read [AGENTS.md](AGENTS.md) before editing. Short version:

- One writer lease per `primitives/<name>/` or `templates/<name>/`.
- `pyproject.toml` and `uv.lock` are serialized to the platform lease (`CODEOWNERS`). Do not edit them from a package lease unless the coordinator includes that path.
- Branch shape: `agent/<id>/<package-or-template>/<slug>`.
- Author agent and judge agent are different processes. CI green is not a merge verdict.

## Not in this lane

`agentcore-session` is still a stub. Memory, guardrails, approvals, context, and recovery live on the shelf. The invoice desk imports them. Memory-via-Gateway is still an open decision (DESIGN §7). There is no live Runtime PASS in this tree.

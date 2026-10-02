# agentcore-standards

Standards library for coding agents and humans building on [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html). This repository holds versioned Python primitives, runnable agent templates, and the eval harness those templates share. It is not a hosted platform.

Normative rules live in [docs/DESIGN.md](docs/DESIGN.md). Path leases for parallel agents live in [AGENTS.md](AGENTS.md) (DESIGN §8).

Lane A is the root of every later stack: `agentcore-tracing`, `agentcore-eval`, and `templates/minimal-agent`, with one golden eval. `agentcore-tools` is implemented. Session, memory, and guardrails are path stubs only.

## Layout

```
packages/agentcore-tracing/     OTEL span names, hashed session id, cost attributes, JSON turn logs
packages/agentcore-eval/        RuntimeHarness, verdicts, suite runner, in-memory harness, Runtime client
templates/minimal-agent/        BedrockAgentCoreApp entrypoint plus a harness binding (an app, not a PyPI lib)
packages/agentcore-session/     stub (lane B)
packages/agentcore-tools/       registry, Gateway Lambda targets, idempotency (lane C)
packages/agentcore-guardrails/  stub (lane D)
packages/agentcore-memory/      stub (lane E)
templates/agent-with-tools/     stub
templates/agent-with-memory/    stub
templates/multi-agent/          stub
templates/human-in-the-loop/    stub
experiments/                    messy drafts allowed; templates and packages must not import them
docs/DESIGN.md                  team standards
docs/capability-maps/           how to drive a template and what observable proves it
docs/evals/                     eval pack index and the hill-climbing rhythm
docs/skills/pstack-vs-agentcore.md   pstack skill to run, and the AgentCore skill if one exists
skills/                         verify, judge, lease, encode-miss, capability map
```

## Two different things named like a harness

| Name | What it is |
| --- | --- |
| `BedrockAgentCoreApp` | The server process AgentCore Runtime hosts. `@app.entrypoint` is `POST /invocations`. |
| `RuntimeHarness` | The eval client: `start`, `invoke`, `capture_traces`, `tear_down`. |
| `InMemoryRuntimeHarness` | Calls the entrypoint in-process and keeps its spans. Default for the golden eval. |
| `AgentCoreRuntimeHarness` | Calls the Runtime **service** (`InvokeAgentRuntime`) when environment credentials exist. |

Evals stay on `RuntimeHarness`. Replacing the hosted container later re-wraps the entrypoint. It does not rewrite the eval.

## Install

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --all-packages
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

- One writer lease per `packages/<name>/` or `templates/<name>/`.
- `pyproject.toml` and `uv.lock` are serialized to the platform lease (`CODEOWNERS`). Do not edit them from a package lease unless the coordinator includes that path.
- Branch shape: `agent/<id>/<package-or-template>/<slug>`.
- Author agent and judge agent are different processes. CI green is not a merge verdict.

## Not in this lane

`agentcore-session`, `agentcore-memory`, and `agentcore-guardrails` are README stubs so later agents have stable paths. Do not implement them here. `agentcore-tools` lives in `packages/agentcore-tools`. Memory-via-Gateway is still an open decision (DESIGN §7).

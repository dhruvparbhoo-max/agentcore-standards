# agentcore-standards

Standards library for coding agents and humans building on [Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/what-is-bedrock-agentcore.html). This repository holds versioned Python primitives, runnable agent templates, and the eval harness those templates share. It is not a hosted platform.

Normative rules live in [docs/DESIGN.md](docs/DESIGN.md). Path leases for parallel agents live in [AGENTS.md](AGENTS.md) (DESIGN §8).

Lane A is the root of every later stack: `agentcore-tracing`, `agentcore-eval`, and `templates/minimal-agent`, with one golden eval. Session, tools, memory, and guardrails are path stubs only.

## Layout

```
packages/agentcore-tracing/     OTEL span names, hashed session id, cost attributes, JSON turn logs
packages/agentcore-eval/        RuntimeHarness, verdicts, suite runner, in-memory harness, Runtime client
templates/minimal-agent/        BedrockAgentCoreApp entrypoint plus a harness binding (an app, not a PyPI lib)
packages/agentcore-session/     stub (lane B)
packages/agentcore-tools/       stub (lane C)
packages/agentcore-guardrails/  stub (lane D)
packages/agentcore-memory/      stub (lane E)
templates/agent-with-tools/     stub
templates/agent-with-memory/    stub
templates/multi-agent/          stub
templates/human-in-the-loop/    stub
experiments/                    messy drafts allowed; templates and packages must not import them
docs/DESIGN.md                  team standards
docs/capability-maps/           how to drive a template and what observable proves it
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

## Evals

The golden eval is `minimal-agent.golden-turn` in `templates/minimal-agent/evals/golden_turn.py`. It sends two turns on one session and checks the deterministic `pong:` completion, the `agent.turn` / `model.invoke` span tree, cost attributes, and structured logs.

Local path (no AWS account):

```bash
uv run pytest templates/minimal-agent/tests/test_golden_eval.py -m "not runtime"
```

That run uses `MinimalAgentHarness`, which calls the entrypoint in-process. Evidence JSON is written under the pytest `tmp_path` for the test, or pass your own directory when you call `run_suite` yourself:

```bash
PYTHONPATH=templates/minimal-agent/src uv run python - <<'PY'
from pathlib import Path
from agentcore_eval import run_suite
from minimal_agent import AGENT_VERSION, MinimalAgentHarness

report = run_suite(
    Path("templates/minimal-agent/evals"),
    harness_factory=MinimalAgentHarness,
    agent_version=AGENT_VERSION,
    evidence_dir=Path("evidence"),
)
print([(item.eval_name, item.status.value, item.evidence_path) for item in report.verdicts])
PY
```

`evidence/` is gitignored.

### Real AgentCore Runtime

Same eval, different harness. Copy `.env.example` to `.env` and fill values locally. Do not commit them. There are no resource ARNs in git.

Required environment variables:

- `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` (dev account; evals use that same account)
- `AWS_REGION`
- `AGENTCORE_RUNTIME_ARN` (the deployed runtime identifier)
- `AGENTCORE_SPAN_LOG_GROUP` (CloudWatch log group name for span collection)
- `AGENTCORE_RUNTIME_QUALIFIER` (optional endpoint qualifier)

```bash
uv run pytest -m runtime
```

The GitHub workflow `.github/workflows/runtime-evals.yml` runs that marker and exits cleanly when those values are unset. A local pass on the in-memory harness is not an independent Runtime verdict. Auto-merge still waits on a separate judge (DESIGN §4.2 and §8).

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

`agentcore-session`, `agentcore-tools`, `agentcore-memory`, and `agentcore-guardrails` are README stubs so later agents have stable paths. Do not implement them here. Memory-via-Gateway is still an open decision (DESIGN §7).

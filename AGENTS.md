# Agent operating rules

Read [docs/DESIGN.md](docs/DESIGN.md) sections 1, 4, and 8 before writing code. This file is the lease card. The design doc is the norm.

pstack (poteto-mode and its playbooks) is the general method. AgentCore skills under `skills/` add only the RuntimeHarness, judge, lease, gate, eval-dataset, tool-register, loop-verifier, and experience-to-gate steps. The overlap map is [docs/skills/pstack-vs-agentcore.md](docs/skills/pstack-vs-agentcore.md). Do not add a skill that restates pstack. Playbooks distilled from elsewhere live under `docs/` with attribution in [docs/attribution/bojieli-ai-agent-book.md](docs/attribution/bojieli-ai-agent-book.md). Hill-climbing stays the poteto Hillclimb playbook; the command sequence on this repo is [docs/evals/hill-climbing.md](docs/evals/hill-climbing.md). There is no `agentcore-hill-climb` skill.

This repo is **agentcore-standards**: a Python standards library for Amazon Bedrock AgentCore. It is not a platform product. Python 3.12 only. uv workspace, hatchling for publishable packages, templates as applications.

## Glossary

- **AgentCore Runtime** is the AWS service. The real eval path calls `InvokeAgentRuntime`.
- **`BedrockAgentCoreApp`** (`bedrock-agentcore` ≥ 1.24) is the process that service hosts. Decorate the turn function with `@app.entrypoint`. Do not use `bedrock-agentcore-starter-toolkit`.
- **`RuntimeHarness`** is our eval client: `start`, `invoke`, `capture_traces`, `tear_down`. `InMemoryRuntimeHarness` calls the entrypoint in-process. `AgentCoreRuntimeHarness` calls the service. Evals target the protocol, not a particular host.

## Layout

Shared libraries live under `primitives/<name>/` (for example `primitives/tracing`). Distribution names (`agentcore-tracing`) and import names (`agentcore_tracing`) stay stable. `patterns/` arrives in later PRs. `templates/` and `experiments/` stay in place until then.

## Leases

One writer per path prefix. Scouts may read anything. Writers need a lease.

| Path | Lane | Status |
| --- | --- | --- |
| `primitives/tracing/` | A | implemented |
| `primitives/eval/` | A | implemented |
| `templates/minimal-agent/` | A | implemented |
| `primitives/session/` | B | stub; actor headers are `agentcore-identity` |
| `primitives/tools/` | C | implemented (registry, compact, cite, catalog) |
| `primitives/guardrails/` | D | implemented; no Runtime PASS |
| `primitives/memory/` | E | implemented on the guard; no Runtime PASS |
| `primitives/identity/` | H | implemented |
| `primitives/approvals/` | I | implemented |
| `primitives/context/` | J | implemented |
| `primitives/recovery/` | K | implemented |
| `primitives/completion/` | L | implemented |
| `primitives/langchain/` | M | implemented; model providers stay outside |
| `templates/agent-with-tools/` | F | invoice desk offline; imports the shelf; no Runtime PASS |
| `templates/agent-with-memory/` | F | stub |
| `templates/multi-agent/` | F | stub |
| `templates/human-in-the-loop/` | F | stub |
| `docs/`, `scripts/`, `.github/` | G | docs and gates |
| `pyproject.toml`, `uv.lock` | platform | serialized; one owner |

`CODEOWNERS` lists each of those paths. The GitHub team is `@agentcore/platform` until real teams exist. The coordinator lease is still one agent per path even while the team name is shared.

Rules:

1. Branch: `agent/<id>/<package-or-template>/<slug>`. One package **or** one template per PR.
2. Do not edit another lease. If you need a new package API, stop and report the blocker.
3. Do not edit `pyproject.toml` or `uv.lock` unless your lease includes the platform manifest. Adding a workspace member is a platform change. Declare every workspace dependency explicitly in the member that imports it.
4. Templates import packages. They do not copy package source. `scripts/check_boundaries.py` fails the build when they do.
5. `experiments/` may be messy. Nothing under `templates/` or `primitives/` may import it. The same script fails the build when they do.
6. No resource ARNs, account ids, or secrets in git. `.env.example` is names only.
7. Do not declare done from `ruff` / `mypy` / unit tests. Those are necessary. A ship verdict is PASS or PASS+NOTES from a **different** process that re-runs the Runtime eval. CI green is not that verdict. No extra human approval on top of a PASS / PASS+NOTES. FAIL or missing evidence blocks merge.
8. Evals run in the same AWS account as dev. Isolate with agent versions, namespaces, and IAM paths.
9. Do not land a stack tip if a lower PR lacks an independent Runtime verdict.

## Verify

```bash
uv sync --all-packages
uv run ruff check .
uv run mypy
uv run pytest -m "not runtime"
uv run python scripts/check_boundaries.py
```

Independent judge (mock path, no AWS). Evidence is `evidence/judge/verdict.json`. Full sequence: [docs/eval-pass-path.md](docs/eval-pass-path.md).

```bash
PYTHONPATH=templates/minimal-agent/src uv run python -m minimal_agent.judge --evidence-dir evidence/judge
```

Real Runtime: add `--harness runtime` after `AWS_REGION`, `AGENTCORE_RUNTIME_ARN`, and `AGENTCORE_SPAN_LOG_GROUP` are set. An access key and its secret are a pair; a role needs neither. Missing settings write `SKIPPED` and the runtime judge exits 1. `SKIPPED` is not a ship verdict. `.github/workflows/runtime-evals.yml` runs that judge and fails closed. This repo does not contain a live Runtime PASS.

## Next agents

`agentcore-tools` and the offline eval pack are already on main without an independent Runtime PASS. That landing is a recorded miss, not a precedent.

Do not start a writer on `agentcore-session`, `agentcore-guardrails`, `agentcore-memory`, or an unfinished template until a coordinator leases a free path **and** a separate process records `PASS` or `PASS+NOTES` for `minimal-agent.golden-turn` on `AgentCoreRuntimeHarness`. Scouts may write under `docs/capability-maps/` only.

If your task needs `agentcore-session` and `agentcore-tools` in one PR, split it. Memory writes go through guardrails. The shelf in DESIGN §2.8 is not an independent Runtime PASS. `templates/agent-with-tools` imports that shelf. The other domain templates stay stubs.

## Hill-climbing

Once Runtime and tracing are hooked up, harness changes follow [docs/evals/hill-climbing.md](docs/evals/hill-climbing.md): source and tag cases, split optimization from holdout, record a baseline, make one harness change, check regressions, human review, then promote or prune. `uv run python -m agentcore_eval.hillclimb steps` prints the commands. A climb diff is not an independent Runtime verdict. This repo has not recorded a production climb.

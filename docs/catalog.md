# Pattern catalogue

Start here when you think you need an agent. This page does not claim a live AWS run.

## Is a workflow enough?

If the steps of the task never change, use a workflow and call a model only where a real choice is needed. An agent is for work that has to choose a tool, retrieve a document, or wait for a person in a way the steps cannot name in advance.

[Anthropic, Building effective agents](https://www.anthropic.com/engineering/building-effective-agents).

A workflow in this repo is still a pattern folder with `pattern.yaml`, but its `framework` can be `harness` and its tools can be an empty list. Do not add a second agent so the first can "think twice" over the same transcript.

## Which pattern

| If the job is | Use | Folder |
| --- | --- | --- |
| Copy a known shape | The starter kit | `patterns/_template/` |
| Answer from company policies, cite the source, or say the empty sentence | Policy Q&A | `patterns/policy-qa/` |
| Send, spend, delete, or change, and a person must decide | Human approval | `patterns/human-approval/` |
| An event should become a job, then an agent, and a risky action waits | Ambient | `patterns/ambient/` |

Every pattern in that table has the twelve kit items. None of them has a live Runtime PASS. Offline tests (ruff, mypy, `pytest -m "not runtime"`, `check-kit`) are necessary and not a ship verdict.

## Shared pieces those patterns use

| Piece | Where |
| --- | --- |
| Front door (identity, session binding, quotas, kill switch, audit) | `primitives/front-door/`, `infra/constructs` |
| `build_agent` (guard, untrusted tags, pause, tracing) | `primitives/agent/` |
| Gateway tool folder | `primitives/gateway-tools/` (`_template`, `submit_change`) |
| Operating model and runbooks | `docs/ops/operating-model.md`, `docs/runbooks/` |

## Not a pattern yet

- A shared streaming UI (`frontend/` is not in the tree).
- A second agent that the first authenticates to with IAM (the multi-agent rules are in [library.md](design/library.md); `templates/multi-agent/` is still a stub).
- Prompt caching on.
- Separate AWS accounts for dev and prod.
- A live trigger Lambda and DynamoDB job table (ambient uses an in-process `JobStore`).
- The Bedrock Guardrails **service** (production-check still refuses because `guardrails_service` is off).

## Templates that remain

`templates/minimal-agent/` and `templates/agent-with-tools/` still run their offline judges. They are not patterns. New work copies `patterns/_template/`, not those folders.

`templates/human-in-the-loop/` is gone; use `patterns/human-approval/`. `templates/multi-agent/` is still a stub.

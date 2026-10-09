# Coverage review

Reviewed 8 October 2026 on `main` after the move from `packages/` to `primitives/`, then updated the same day for the CLI, front door, and container decisions. Updated again on 9 October 2026 after the starter kits, front door, three patterns, and catalogue landed on this stack. This page compares the tree with the pattern-library layout. It does not claim a live AWS run. A ship verdict is still a separate Runtime check. See [the library design](library.md) for the choices, [the catalogue](../catalog.md) for which pattern to copy, and [the pattern design outline](pattern-design-template.md) for what each pattern page must contain.

## After steps 3–8 (9 October 2026)

Status words still mean Exists / Partial / Missing. Nothing below is a Runtime PASS.

| Piece | Status | What is in the repo now |
| --- | --- | --- |
| `primitives/front-door/` | Exists | Verified caller, session binding, quotas, kill switches, audit, cost, local stack. No live Runtime call. |
| `infra/constructs/` | Exists | Foundation, front door, network, DNS Firewall, alarms, per-agent model profiles. Synthesized in tests; not deployed. |
| `patterns/_template/` | Exists | Twelve-item kit. |
| `patterns/policy-qa/` | Exists | Trusted retrieve, citations, empty sentence. Offline golden score. |
| `patterns/human-approval/` | Exists | Four asks, `submit_change`, pause token. Offline golden pause + resume unit tests. |
| `patterns/ambient/` | Exists | Event to job to agent. In-process `JobStore`. No live SQS/Lambda. |
| `docs/catalog.md` | Exists | Asks whether a workflow is enough, then names the four folders. |
| `patterns/minimal-agent/` | Exists | Golden-eval ping agent, moved from `templates/minimal-agent/`. No Runtime PASS. |
| `docs/runbooks/` | Exists | Runtime, kill switch, quotas. |
| `docs/ops/operating-model.md` | Exists | TBD placeholders; copied from ENTERPRISE. |
| Live Runtime PASS | Missing | This repo still has none. `SKIPPED` is not a ship verdict. |
| `frontend/` | Missing | No shared UI. |
| Bedrock Guardrails service | Missing | `controls.guardrails_service` is still off in prod; production-check refuses. |
| `templates/` | Removed | Invoice desk, multi-agent stub, and human-in-the-loop stub deleted. Ping agent moved to `patterns/minimal-agent/`. |
| `experiments/` | Removed | The drafts folder is gone. |

The tables below are the 8 October snapshot and are kept so the gap list that drove the stack is still readable. Where they say Missing for the front door, the kit, or the first three patterns, the table above is the later fact.

Status words: **Exists** means the target is already in the tree. **Partial** means a piece is here, but not in the target shape. **Missing** means it is not in the tree.

`skills/` stay. This page only records what the tree held when it was written.

## Layout

| Piece | Status | What is in the repo now |
| --- | --- | --- |
| `primitives/` | Partial | Tracing, eval, approvals, tools, guardrails, memory, identity, context, recovery, completion, and LangChain are real packages. Session is an empty stub. Front door, triggers, a Gateway tool folder template, auth beyond headers, and a switchable agent loop are not here. |
| `infra/constructs/` | Missing | No CDK app. No construct per primitive. The AgentCore CLI's CDK is not wired in. |
| `patterns/<name>/` | Missing | No pattern folder, no `pattern.yaml`, no generated `agentcore.json`, no per-pattern `docs/design.md`. |
| `docker/` and `.devcontainer` | Missing | No shared base images, no Docker Compose file, no dev container. |
| `frontend/` | Missing | No shared UI. |
| `docs/catalog.md` | Missing | No catalogue page that asks whether a workflow is enough. |
| `docs/design/` | Partial | This review, the library page, and the pattern outline are the start. Older design pages are removed where the library page replaces them. |
| `docs/runbooks/` | Missing | Kill-switch runbooks are part of the front door design and are not written yet. |
| CI | Partial | Every push and pull request runs ruff, mypy, `pytest -m "not runtime"`, the boundary checker (including the rule that blocks a resource ARN in git), and the in-process judges. A second workflow runs the Runtime judge and fails closed when settings are missing. There is no image build, no image scan, no doctor or verify command, and no deploy, end-to-end test, and teardown stage. |

## Primitives

| Primitive | Status | What is in the repo now |
| --- | --- | --- |
| Front door | Missing | No single entry point. Nothing checks a verified user, binds a session id, enforces quotas, serializes a session, or writes a cost and audit row per call. |
| Tracing | Exists | OpenTelemetry span names, hashed session id, structured turn logs, and a length-based cost estimate at zero USD. That estimate is not a cloud bill. |
| Eval | Partial | `RuntimeHarness` (`start`, `invoke`, `capture_traces`, `tear_down`), in-process and Runtime harnesses, an offline golden pack, and a judge that writes `verdict.json`. No live Runtime PASS is stored in the repo. No source-backed score at 0.7, and no messy policy fixture set. |
| Approvals | Partial | Single-use tokens bound to the tool, the argument hash, and the actor. The approver cannot be the actor. Expired tokens do not spend. There is no queue of stuck approvals, no approval screen, no audit store, and no approval container image. |
| Triggers | Missing | Nothing receives an event, writes a job, or starts an agent from a queue. No shared triggers image. |
| Gateway tools | Partial | `primitives/tools` is a local registry: deny until a permit, Cedar statements, Lambda targets, schema checks, idempotency keys, compact, cite, and a name-only catalog. MCP server targets can be named and do not sync. There is no `gateway-tools/_template/`, no per-tool container image, and no AWS Agent Registry client. The local registry is not the long-term catalogue. |
| Auth | Missing | No Cognito sign-in, no token vault, and no on-behalf-of exchange. |
| Identity | Partial | Reads the Runtime actor header and the session header. It does not decide whether the agent acts as the user or as itself, and it does not bind the session id to the user. |
| Memory | Partial | In-process short-term events and long-term records. A guard screens the write. Retrieve is lexical and stays inside one actor. It does not call AgentCore Memory. It does not check facts for poisoning, tag a source, or offer a user delete path. Tests do not share one memory resource. |
| Knowledge | Missing | No Gateway knowledge-base target. `Corpus.retrieve` is a lexical search over text the caller passes in. The policy pattern will not use a custom search tool. |
| Agent loop | Partial | `primitives/langchain` calls LangChain `create_agent` with the local tool registry. The caller supplies the model. There is no `build_agent(config)` with `run`, `stream`, and `pause_for_human`, and no `strands` or `harness` switch. |
| Guardrails | Partial | Local policy blocks injection-shaped text and secret-shaped text, and masks email, phone, and national-id shapes. A required Bedrock backend that is missing blocks the turn. No Runtime PASS. Tool results are not masked as a separate step. |
| Context | Partial | Assembles system text, a state bar, and the user turn. Tool results are dropped first when the budget is tight. Counts use a length heuristic. No model-token compaction yet. |
| Recovery | Exists | Capped backoff with jitter, a circuit breaker, an attempt cap, an elapsed cap, and an in-flight cap. Fatal results are not retried. The model access layer that should call it does not exist yet. |
| Completion | Exists | A verifier accepts a claim only with evidence, and only when the verifier is not the proposer. |
| LangChain | Exists | Adapter from the local tool registry to `create_agent`. Model providers stay outside the package. This is the code the default framework will sit on. It is not the front door. |
| Session | Missing | Stub directory only. No package. Idle and lifetime limits are not applied. The design default for chat is 5 minutes idle and 30 minutes maximum, which nothing sets. |
| Model access | Missing | No shared caller for backoff, a fallback model, a UK or EU geographic profile, a per-agent model key, or team tags. |

## Containers and the CLI

| Piece | Status | What is in the repo now |
| --- | --- | --- |
| AgentCore CLI | Used for deploys | `pattern.yaml` generates `agentcore.json` (step 3). |
| AgentCore CLI | Missing | No `@aws/agentcore` install, no `agentcore.json`, no generator from `pattern.yaml`. |
| Docker base images | Missing | No `docker/base-agent`, `docker/base-lambda`, or `docker/base-tool`. |
| Agent images | Missing | No Dockerfile. Nothing builds or pushes an ARM64 image to ECR. |
| Lambda images | Missing | No `DockerImageFunction`. Triggers, the front door, and approvals have no shared images. |
| Gateway tool images | Missing | Tools are Python modules, not one image per tool. |
| Local compose and `make local` | Missing | No compose file, no DynamoDB Local or LocalStack stand-in, no target that runs sample events in a container. |
| Image scanning | Missing | CI does not run Trivy, and there is no ECR repository to scan. |

## Pattern kit

Every pattern is supposed to ship with the same twelve pieces. None of that kit exists as a pattern yet. Pieces that already exist elsewhere are marked partial.

| Kit item | Status | What is in the repo now |
| --- | --- | --- |
| README | Missing | Template READMEs exist. Pattern READMEs do not. Nothing lists `docker ps` as a prerequisite. |
| `pattern.yaml`, including memory and `deployment: docker` | Missing | No schema file is enforced. The schema is specified in the library page only. |
| Prompt files | Partial | The invoice desk keeps a prompt module under `templates/agent-with-tools/`. Prompts are not a required file per pattern. |
| Cedar limits on tools | Partial | The tools package can sync permit and forbid statements. No pattern ships a Cedar file. |
| Human approval on send, spend, delete, and change | Partial | The approval package can gate one tool call. Nothing forces those four action classes to pause. |
| Tracing | Partial | The tracing package exists. Patterns do not stamp a release id yet, because patterns do not exist. |
| Unit tests and contract tests | Partial | Primitive tests and the invoice desk tests exist. No pattern `tests/` tree, and no contract test between a pattern and a tool schema. |
| Golden set | Partial | The shared eval pack and `minimal-agent.golden-turn` exist. No `patterns/<name>/eval/golden_set.json`, and no messy policy set with a 0.7 source-backed pass mark. |
| Sample events | Missing | No `events/` folder. |
| Untrusted-input tags, guardrails, and Secrets Manager | Partial | Guardrails exist. Secrets are forbidden in git. There is no shared tag wrapper and no Secrets Manager helper. |
| Step, timeout, and retry limits | Partial | Recovery caps exist in code. Nothing requires each pattern to set them in config. Chat does not use the 5 minute / 30 minute defaults. |
| One CDK deploy and teardown | Missing | No construct, no ARM64 image push, and no teardown stage. Teardown-always and the shared test memory are not in CI. |

## First patterns

| Pattern | Status | What is in the repo now |
| --- | --- | --- |
| Company-policy questions and answers | Missing | No Gateway knowledge-base target, no tenant or role filter from the verified login, and no answer that says "I couldn't find this in the policies" when search is empty. |
| Human approval, four ways of asking a person | Missing | `templates/human-in-the-loop/` is a stub README. The four approaches (hook, tool context, Step Functions, MCP elicitation) are not in the tree. |
| Ambient agent (event, then job, then agent, then approval) | Missing | No trigger, no job table, no sample events. |

## Shared behaviour

| Behaviour | Status | What is in the repo now |
| --- | --- | --- |
| How agents call each other | Partial | The rule is now in the library page. `templates/multi-agent/` is a stub. No authenticated agent-to-agent call exists in code. No design page has a session budget. |
| Job queue separate from agent memory | Missing | No queue and no idempotency table. Memory is the only state package, and it is in-process. |
| Duplicate events | Partial | Tool calls replay one idempotency key. Events have no store, so a repeated event is not yet a no-op. |
| Retries and timeouts | Partial | Tool and recovery helpers classify retryable and fatal faults. The front door's model access layer is missing, so throttling, fallback, and the regional profile have nowhere to live. |
| Stuck approvals | Partial | Tokens expire and then refuse to spend. Nothing records a waiting job, resumes it after the session dies, or sweeps an approval nobody answered. |
| Release bundle and named endpoints | Missing | Packages use their own version numbers. Nothing pins prompt, model, tools, policy, and image digest as one release, or pins a named AgentCore endpoint. |
| Checkpoints | Missing | Session disk is treated as scratch in the docs. Progress is not saved on a job row. |
| Audit log separate from traces | Missing | Traces and turn logs exist. Nothing writes an audit entry per call, or a tamper-resistant record of who approved a send, spend, delete, or change. |
| Kill switch | Missing | `StopRuntimeSession` is what the Runtime judge calls on teardown. No per-agent or per-tool flag is read on the way in. No runbook. |
| Header allowlist and MCP session header | Missing | No CDK runtime config. Nothing records `requestHeaderAllowlist` or chooses `Mcp-Session-Id` for MCP. |
| Code Interpreter | Missing | No pattern runs model-written code. The VPC mode, DNS firewall, and IMDSv2 rule have nowhere to attach yet. |
| Doctor, verify, production mode | Missing | No command checks the toolchain before deploy, re-checks controls after deploy, or refuses a production deploy that skips a control. |

## What stays on purpose

| Piece | Status | Why it is still here |
| --- | --- | --- |
| `templates/` | Exists | `minimal-agent` and the invoice desk run today. Memory, multi-agent, and human-in-the-loop templates are stubs. A later step replaces them with patterns. |
| `experiments/` | Exists | Allowed to be messy. Templates and primitives must not import it. |
| `skills/` | Exists | Checklists for the Runtime harness, the judge, leases, eval cases, tool registration, and the miss-to-gate loop. |
| `primitives/tools` local registry | Exists | It is the current deny-by-default helper. The library page points new tools at AWS Agent Registry and the folder template. This package stays until that code change. |
| Playbooks under `docs/tools/`, `docs/runtime/`, `docs/evals/`, `docs/prompts/`, `docs/ops/` | Exists | They tell a person how to shape a tool, a case, or a recovery. The library page does not repeat them. |

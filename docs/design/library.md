# Library design

This is the one page for choices every pattern shares. A pattern's `docs/design.md` says how that pattern uses these choices. It does not invent a second rule. The outline for that page is [pattern-design-template.md](pattern-design-template.md). What the repo already contains is [coverage-review.md](coverage-review.md).

This page sets the design. It does not claim a live AWS run, and it does not store a Runtime PASS. The ship bar below is how a later change gets to merge.

Words used here, once:

- **AgentCore Runtime** is the AWS service that runs an agent. A **session** is one conversation on that service. Each session gets its own small virtual machine (a **microVM**). Disk and RAM on that machine disappear when the session stops, unless we saved the data somewhere else.
- The **front door** is our one entry point. Every chat, API, event, schedule, and eval call goes through it before a Runtime session starts.
- **Gateway** is AgentCore's front for tools and knowledge bases. **Cedar** is the policy language that allows or denies a tool call.
- **Agent Registry** is the AWS catalogue of agents and tools. New tools are registered there. We do not keep a second catalogue.
- **Idempotency** means doing the same request twice has the same effect as doing it once.
- A **golden set** is a file of example requests and the outcomes we expect.
- An **endpoint** is a name that points at one immutable version of a Runtime.
- **On-behalf-of** means the agent exchanges the user's sign-in token for a short-lived token that can only do what that user can do.
- A **release** is one bundle of prompt files, model id, tool list, and Cedar policy.
- A **checkpoint** is the saved progress of a job, so a new session can continue it.
- A **base image** is a shared container image that other Dockerfiles start from, so each of those files stays short.

## What the repo is

This repo is a pattern library for AgentCore. Python 3.12 only. We build on the [AgentCore CLI](https://github.com/aws/agentcore-cli) (`npm` package `@aws/agentcore`) and on AWS-managed pieces. `pattern.yaml` generates the CLI's `agentcore.json`, and `agentcore deploy` builds and deploys from it.

Shared code lives in `primitives/`. The first new package in that set is `primitives/front-door/`. One CDK construct per primitive will live in `infra/constructs/`. The CLI's CDK handles AgentCore resources (runtime, memory, gateway, knowledge base, endpoints) inside our CDK app. We do not hand-write those resources a second time. Our constructs own the front door, the job table, the queue, and the container functions.

Each pattern will live in `patterns/<name>/` with a README, `pattern.yaml`, `agent/`, a Dockerfile, prompt files, `infra/`, `tests/` (including `tests/e2e/`), `eval/golden_set.json`, `events/`, and `docs/design.md`. `pattern.yaml` generates `agentcore.json`. Account ids stay in the environment. They are not written into git.

A shared UI will live in `frontend/`. A catalogue will live in `docs/catalog.md`.

`templates/`, `experiments/`, and `skills/` stay until a later change retires them. Templates import primitives. They do not copy primitive source. Nothing under `templates/` or `primitives/` imports `experiments/`.

The first three patterns, when they are built, are:

1. Company-policy questions. The agent searches through a Gateway knowledge-base target, cites the source, and says "I couldn't find this in the policies" when search returns nothing. A trusted wrapper adds the tenant and role filter from the verified login, so the model cannot choose another tenant's documents. [Multi-tenancy sample](https://github.com/aws-samples/sample-agentcore-and-multitenancy-blog). There is no custom `search_policies` tool.
2. Human approval. The pattern shows four ways to ask a person. The pause and the token rules are the ones in this page.
3. Ambient work. An event becomes a job, the job runs an agent, and a risky action waits for approval.

If the steps of a task never change, use a workflow and call a model only where a real choice is needed. The catalogue page will ask that first. [Anthropic, Building effective agents](https://www.anthropic.com/engineering/building-effective-agents).

## Ship bar

A ship verdict is `PASS` or `PASS+NOTES` from a separate process that re-runs the Runtime eval. The sequence is [eval-pass-path.md](../eval-pass-path.md). `FAIL` or missing evidence blocks merge. `SKIPPED` is missing evidence. Notes on a pass become a follow-up, not a silent waiver.

Ruff, mypy, and `pytest -m "not runtime"` stay required. A green CI job does not ship the change. No extra human approval sits on top of `PASS` or `PASS+NOTES`.

Evals run in the same AWS account as dev. Isolate them with the agent version, the memory namespace, and the IAM path. A later promotion design can split accounts. This page does not do that. [AWS Prescriptive Guidance, enterprise agent accounts](https://docs.aws.amazon.com/prescriptive-guidance/latest/agent-ops-maturity-roadmap-for-enterprise-ai/introduction.html) is the reference for that later split.

A repeated miss becomes a failing eval or a CI gate, then the fix. A doc or a skill comes after the gate, and only for a judgment the gate cannot check. See [the experience loop](../ops/experience-loop.md).

## Front door

`primitives/front-door/` is in the first build. Chat, API, schedule, event, and eval all call it. It is the only way to start a session. [Agent platform sample](https://github.com/aws-samples/sample-agent-platform-with-agentcore).

On every call the front door:

1. Checks the verified user. A background job with no live user uses the service identity recorded on the job, including whose consent was stored.
2. Binds the session id to that user. The id is at least 33 characters. A shorter id is rejected. A session id that belongs to someone else is rejected. [Runtime sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html).
3. Allows one in-flight call per session. A second call waits or is refused. Two callers must not share one warm microVM.
4. Checks quotas and rate limits for the user, the team, and the agent. Over quota, the call is refused and no session starts.
5. Reads the kill switch for that agent and for each tool the call would use. Switch off means the call stops. Runbooks for these switches live in `docs/runbooks/`.
6. Enforces the caps on turns, steps, and spend from `pattern.yaml`.
7. Gets an on-behalf-of token for tool calls when `identity.acts_as` is `user`. The agent's rights and the user's rights stay separate. [On-behalf-of token exchange](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/on-behalf-of-token-exchange.html).
8. Calls the model through one access layer: capped backoff, the fallback model, and a UK or EU geographic inference profile. Each agent has its own model key. Resources carry a team tag, in the same spirit as Loom's group tag. [Loom](https://github.com/awslabs/loom). A cross-region profile adds capacity. It is not failover by itself. [Cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html). [Geographic profiles](https://docs.aws.amazon.com/bedrock/latest/userguide/geographic-cross-region-inference.html).
9. Writes a cost record and an audit entry for the call: who, which agent, release id, latency, turns, and cost. The agent role cannot delete or overwrite the audit entry.

The Runtime role for a session holds only what that user may access. A person with a session can read the credentials inside that microVM. [Agent platform sample](https://github.com/aws-samples/sample-agent-platform-with-agentcore).

Chat sessions use a 5 minute idle timeout and a 30 minute maximum lifetime (`idle_timeout_s` 300, `max_lifetime_s` 1800). Background jobs set their own values in the pattern and say why. The service default is 15 minutes idle and 8 hours maximum, and a microVM cannot exceed 8 hours. [Lifecycle settings](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html). While a background step is running, the process answers the Runtime ping as HealthyBusy so an idle timeout does not kill a busy session.

Long work that outlives an HTTP call is submit-then-poll. The caller receives a job id. The UI polls job status. The front door does not hold the HTTP connection open for an approval wait.

## How a turn is built

`build_agent(config)` reads `pattern.yaml` and returns an agent with `run`, `stream`, and `pause_for_human`. `framework` is one of:

- `create_agent`, the default. This is LangChain's tool-calling loop. Model providers stay outside the LangChain package. The caller passes the model the config names.
- `strands`, the code alternative. The managed extras from AWS tend to arrive here first. The switch stays covered by tests.
- `harness`, the AgentCore managed loop. The pattern describes the model, prompt, tools, and limits in config, and AWS runs the loop. The harness is built on Strands. A later export can turn that config into Strands code when the pattern outgrows config. The generator writes the harness config to `app/<harness name>/harness.json` with `system-prompt.md` beside it, which is where the CLI looks for it.

Every framework still enters through the front door. The order inside the session is:

1. The front door has already checked identity, the session binding, quotas, and the kill switch.
2. Run the guard on the user text. A block stops the turn.
3. Assemble context. The state bar, the system text, and the user turn stay. Tool results are dropped first when the budget is tight.
4. Disclose tool names from Agent Registry. Loading a schema does not permit the tool.
5. Call the tool through Gateway. Recovery wraps retryable faults. An approval token is spent inside the handler, after a different person has approved. The on-behalf-of token is the credential for that call.
6. Run the guard on the text the user will see.
7. Write memory only through the memory client.
8. Hand a completion claim to a verifier with a different id.

`stream` exists so a long turn can show progress. The shared front end is not built yet.

## How agents call each other

Start with one agent. Add a second agent only when it brings evidence the first agent cannot see while it is generating. A second pass over the same transcript does not qualify. Parallel search can still be worth the tokens when the task is an open collection and the extra coverage is written down.

When a call is justified:

- The caller authenticates with IAM. It does not forward the user's token.
- The caller sends a structured handoff: task id, sender, recipient, goal, constraints, accepted facts, artifact refs, remaining budget, and the agents already visited. The recipient pulls artifacts by reference.
- The runtime owns the budget and the visited list. A recipient already on that list is rejected. A spent budget stops the job.
- The parent receives the result, not the child's private reasoning.
- Each hop has its own timeout. The recovery circuit breaker stops a failing callee from stalling the caller.
- Free text from another agent is untrusted input. It is tagged and guarded like any other outside text.
- If several workers can finish the same task, the first verified success takes an idempotent lock and the others are cancelled.
- The pattern's design page includes a session budget. Count sessions, not requests. Each specialist holds a microVM until it times out.

[OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/) (ASI07 and ASI08) and the [Agentic AI Lens](https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/appendix-a.html) describe this trust problem.

## Job queue

Job state and agent memory are different stores.

An event (a webhook, a schedule, or a queue message) hits the triggers code. The trigger writes a job row with a conditional put. The key is the idempotency key below. If the row already exists, the trigger stops. The trigger then enqueues the job id. A worker calls the front door with that job id. The worker does not call Runtime directly.

The job row holds status (`queued`, `running`, `waiting_for_approval`, `succeeded`, `failed`, `cancelled`), the release id, the current attempt, the session id for this attempt, the checkpoint, and any approval id. The worker may update that row. The agent does not use the row as a notebook.

The queue and the job table are the triggers store. They are not AgentCore Memory, and they are not the microVM disk.

Chat with `trigger: none` does not grow a queue. The front door call is the job.

## Idempotency

Two layers, and they are not the same key.

**Events.** The idempotency key is the source name plus the event id. A second delivery of that pair finds the existing job and does not start another one. A new event id is a new job, even when the payload looks similar.

**Tools.** A side-effecting tool requires an idempotency key. The first result is replayed when the key is repeated. The same key with different arguments is a fatal conflict and does not run the handler. The handler also uses a natural key (put-if-absent or a version check), because a retried invoke may not see the caller-side key. Retryable failures are not cached. Fatal failures are cached. A timeout is retryable.

Email, payment, and anything that leaves the account do not become safe just because the key repeats. Those actions pause for a person, then perform once.

Every new side-effecting tool needs a double-invoke test: one key, one effect.

The current `primitives/tools` package already replays one idempotency key for its demo tool. That package is the local helper until Agent Registry and Gateway own the catalogue. New patterns register tools in Agent Registry. They do not add a second list beside it.

## Retries and timeouts

Classify the fault, then retry.

| Fault | What we do |
| --- | --- |
| Throttle, connection drop, brief overload | Retry with capped exponential backoff and jitter. Honor a wait time the service sends. |
| Tool timeout or over-budget latency | Retryable. The recovery helper supplies the backoff. |
| Schema rejection, unknown tool, same key with different arguments | Fatal. Do not retry the same call. |
| Same tool fingerprint failing with no new state | Stop that path. Count it as no progress. |
| Model output that fails the schema | Fatal for that step. The model may try a new plan inside the step cap. It may not repeat the failed call unchanged. |

`primitives/recovery` is the shared helper: attempt cap, elapsed cap, in-flight cap, and a circuit breaker. An open circuit does not call the operation. Fatal results do not open the circuit. The front door's model access layer uses this helper. Patterns do not call the model from a one-off client.

Every pattern sets `lifecycle.max_steps`, `lifecycle.timeout_s`, and `lifecycle.max_retries`. A loop without a ceiling can spend the error budget for every other job.

Prompt caching stays off (`model.cache: off`) until the model access layer exists and the static prefix is long enough for the chosen model. When it is turned on, the stable part comes first (tools, then system prompt, then fixed reference docs) and the changing part comes last (dates, user names, retrieved chunks, the new turn). Background and approval patterns use a one-hour cache on tools and the system prompt. Chat uses five minutes. [Bedrock prompt caching](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html).

## Stuck human approvals

Send, spend, delete, and change wait for a person. The agent calls `pause_for_human`. The job status becomes `waiting_for_approval`. The approval token is bound to the tool name, the argument hash, and the actor. `decide` must come from someone who is not the actor. `consume` spends the token once, and only if the tool, the hash, the actor, and the expiry still match.

`risk_tier: high` needs two approvers. Other tiers need one. The screen shows the action, the arguments, and the expiry. A vague "approve?" is not enough, because people click through it. [Agentic AI Lens, appendix A](https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/appendix-a.html).

An approval that waits overnight must not depend on the session still being alive. Chat sessions end after 30 minutes. The waiting state lives on the job row, with a checkpoint. When a person decides, a worker starts a new session through the front door, loads the checkpoint, and either performs the action or records the rejection. If the token expires first, a sweeper marks the job `failed` and does not perform the action. Silence is a no.

The human-approval pattern is where the four ask-the-person approaches are written up (a hook, tool context, a Step Functions wait, and MCP elicitation). All four use this pause, this token, and this expiry. Other patterns do not re-implement the ask. They call `pause_for_human`.

## Where state lives

| State | Store | Lifetime |
| --- | --- | --- |
| Queue and job status, idempotency row, checkpoint, approval id | Triggers store (job table and queue) | Until the job reaches a terminal status, then per the pattern's retention |
| Facts about one user or team | Agent memory, after the guard, scoped to actor and `{agent_version}/{environment}` | Until the user deletes them, or the pattern's memory rule says so |
| Policy documents and other shared knowledge | Knowledge base behind a Gateway target, filtered by tenant and role | Until re-indexed. Not memory. Not a custom search tool. |
| This session's scratch files | MicroVM disk, optional session storage for files that must survive a resume | Disk dies with the microVM unless session storage is configured |
| Debug trace and turn logs | Tracing | `data.log_retention_days` (default 90). Sampled traces are not an audit. |
| Who called, what was decided, which tool ran, who approved, what it cost | Audit store the agent role cannot delete or overwrite. The front door writes one entry per call. | `data.audit_retention_days`, at least as long as the logs. Raise it when the pattern sends, spends, or deletes. |

Memory writes go through `MemoryClient` after the guard. They do not go through Gateway. Gateway fronts tools and knowledge bases. This closes the old open question about a Gateway path for every memory write. The current client is in-process and does not call the AgentCore Memory service yet. The contract stays the client.

A pattern with `lifecycle.resumable: true` writes a checkpoint on the job row after each step (step index, pending action, release id). Conversation text that must outlive the session goes through the memory client, not onto the job row. [Runtime sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html) say structured data beyond the session belongs in AgentCore Memory. We use that for user facts. We use the job row for workflow progress so a queue retry cannot become a second side effect.

`memory.write_policy: validated` means a fact is stored only after the guard, with a source tag (user, tool, or agent). The user can list and delete their records. A one-off search result is not a fact. [OWASP agentic top 10, memory poisoning](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/). `write_policy: off` means the pattern stores no long-term facts. The memory section is still required, so the choice is visible.

Context is not long-term memory. `assemble_context` keeps the state bar, the system text, and the user turn, and drops tool results first. `context.token_budget` and `context.compaction_at` are the pattern's limits. Retrieved chunks stay after the stable prompt prefix. [Anthropic, effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents).

Test runs share one memory resource. AgentCore Memory allows 150 memories per account per region by default. A memory per pull request would use that quota up. [Production notes gathered from teams running AgentCore](https://vindler.solutions/blog/aws-bedrock-agentcore-production-guide). The end-to-end stage reuses that shared test memory. It does not create one.

## Deployment

Deployment is a container image for every independently deployed unit. `pattern.yaml` sets `deployment: docker`. Zip packaging is a later option and is not built now.

One image per unit, not one image per function:

| Unit | Image | Handlers |
| --- | --- | --- |
| Each agent | Its own image | That agent's entrypoint |
| Each Gateway tool | Its own image | That tool only, so permissions and dependencies stay separate |
| Triggers | One shared image | Signal processor, scheduler, and job handlers, each with its own entry point |
| Front door | One image | The front door handlers |
| Approvals | One image | The approval handlers |

Lambda functions use CDK `DockerImageFunction` on these images. There are no zip Lambdas.

Everything builds from two or three shared base images under `docker/`:

- `docker/base-agent` for agent runtimes.
- `docker/base-lambda` for triggers, the front door, and approvals.
- `docker/base-tool` for Gateway tools when their dependencies differ from the Lambda base. If they do not differ, tools use the Lambda base and there are two bases.

Base images pin the Python version and the system packages. They do not use a floating `latest` tag. They run as a non-root user. Per-unit Dockerfiles stay short: they name the base and the entry point.

Agent images are ARM64, because AgentCore Runtime runs that architecture. They are pushed to ECR. On an Intel or AMD machine, `docker buildx` with QEMU builds ARM64 locally.

Developers have Docker locally (Finch on a Mac is the same check). `docker ps` must succeed before a local run or a deploy. The developer path is: build the ARM64 image, push it to ECR, then deploy with CDK and the AgentCore CLI from that machine. A `make local` target runs Docker Compose against the pattern's sample events before anyone deploys.

Docker Compose runs the agent, the tool images, and local stand-ins (DynamoDB Local, and LocalStack where a real AWS API would only get in the way). The repo root has a `.devcontainer` with CDK, the AgentCore CLI, Python, and Node. CI and the end-to-end jobs run inside those same toolchain containers.

CI scans every image with Trivy before the job continues, and the ECR repository has scanning turned on. A high or critical finding fails the job.

The end-to-end stage builds each image once and reuses it for every framework that image can run. It does not rebuild the same pattern image per framework. The harness path deploys from config and does not build a second copy of an image the pattern does not need.

CodeBuild, or an ARM64 GitHub runner, is for CI and the end-to-end stage. It is not the path a developer uses on a laptop. The shape of that CI build follows the FAST CodeBuild script, adapted to our images. [FAST `deploy-with-codebuild.py`](https://github.com/awslabs/fullstack-solution-template-for-agentcore).

If a pattern moves into a private network, the VPC gets endpoints for `ecr.api`, `ecr.dkr`, and S3 so image pulls do not depend on the public ECR address. That is added only when private networking is actually turned on.

Runtime config keeps `requestHeaderAllowlist` in the CDK input on every create and every update. An update replaces the whole runtime config. Leaving the allowlist out drops headers with no error. HTTP and A2A sessions use `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`. MCP sessions use `Mcp-Session-Id`. Using the wrong header starts a new cold session every call. [Runtime sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html).

## Versioning and rollback

A release is one bundle: the prompt files, the model id, the tool names and schema versions, the Cedar policy, and the container image digest that runs them. `pattern.yaml` generates `agentcore.json`, which is the CLI's project file for that bundle. CI stamps a release id from those inputs and writes it on the trace, on the audit entry, and on the job row. Behaviour changes when any part of the bundle changes, not only when Python changes.

AgentCore creates a new immutable Runtime version when the runtime changes. The `DEFAULT` endpoint moves to that new version by itself. A named endpoint stays where you pointed it until you update it. [Runtime versioning and endpoints](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html).

Each environment uses a named endpoint (`DEV`, `PROD`). Customer and event traffic uses that name. It does not use `DEFAULT`.

Rollback points the named endpoint at the previous version. It does not require a new image build. The previous image digest is still the one that version recorded.

A microVM keeps the artifact it was given when it was created. An update does not swap code inside a live session. The session keeps the old artifact until it stops, and the next session gets the new one. [Lifecycle settings](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html). In-flight jobs keep the release id on the job row. A resume calls the endpoint that still serves that release when the fix must not change a job halfway through. New jobs use the endpoint's current target.

Breaking a tool schema (removed field, type change, new required field) bumps the tool's major schema version. Old versions keep working until the patterns that call them have moved. The tool's image and the agent's image ship separately, because they are separate units.

## Security and trust boundaries

**Who the agent is.** `identity.acts_as: user` means a person is signed in and the tool call uses an on-behalf-of token scoped to that user and that tool. `identity.acts_as: service` is for work with no live user, such as an ambient job. The pattern design says whose consent was stored, and where that record lives. A background job does not reuse a leftover user token.

**What may enter the prompt.** User text, retrieved documents, tool results, emails, and another agent's messages are untrusted. Wrap them in a tag that names the source before they reach the model. Run the guard on input and on user-visible output. Cedar decides which tool may run. It does not check every argument. Check arguments against the tool schema, and check model output against `output_schema`, before a write, a send, or a UI render. [OWASP LLM05, improper output handling](https://owasp.org/www-project-top-10-for-large-language-model-applications/2_0_vulns/LLM05_ImproperOutputHandling).

**Tools.** New tools start from the Gateway tool folder template (`gateway-tools/_template/`). Each tool is its own image and its own Agent Registry entry. Deny until this release's policy permits the tool. A forbid wins. One policy engine per release, so an old permit does not outlive it. Tool descriptions are reviewed like code. Names are unique. Outbound calls from a tool stay on an allow-list. Secrets come from Secrets Manager or IAM. They are not written into prompts, memory, logs, fixtures, or git.

**Knowledge.** The policy agent retrieves through a Gateway knowledge-base target. The filter (tenant and role) is added by our code from the verified login. The model does not supply that filter.

**Personal data.** `data.classification`, `data.pii`, and `data.region` say what the pattern touches and where it is processed. Mask personal data in tool results, memory writes, and logs before they are stored. A guardrail on the user message is not a mask for tool arguments or tool results. Apply a sensitive-information filter on those paths too. [Bedrock Guardrails sensitive information filters](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-sensitive-filters.html). Model calls use the EU geographic profile unless the pattern's design page names another region and says why.

**Audit.** Traces are for debugging. They can be sampled and deleted. The front door writes an audit entry on every call. A send, spend, delete, change, or approval adds the action, the argument hash, and the approver. [Agentic AI Lens, appendix A](https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/appendix-a.html).

**Stop.** The front door reads a kill switch per agent and per tool before it starts work. Switch off means the job is `cancelled` and the run returns. `StopRuntimeSession` stops the microVM. A Cedar forbid turns one tool off without a new image.

**Code the model wrote.** Any pattern that runs that code uses AgentCore Code Interpreter in VPC mode, with a DNS firewall, and with IMDSv2 required. The interpreter role is separate and holds only what that run needs. Sandbox network mode is not enough, because DNS lookups have been used to move data out. [Unit 42 on the Code Interpreter network](https://unit42.paloaltonetworks.com/bypass-of-aws-sandbox-network-isolation-mode/).

**Git.** No resource ARNs, account ids, or secrets in the tree. `.env.example` lists names only. The boundary checker fails the build on an ARN marker or a private-key marker.

## The pattern.yaml schema

Each pattern has one `pattern.yaml`. The memory section, the framework, the deployment, and the tool list are required even when memory is off and the tool list is empty. The generator writes `agentcore.json` from this file.

| Field | Required | Meaning |
| --- | --- | --- |
| `name` | yes | Pattern id. Matches the folder name. |
| `owner` | yes | Person or team address accountable for the pattern. |
| `autonomy` | yes | `observer`, `assistant`, `autonomous`, or `orchestrator`. From the [Agentic AI Lens design principles](https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/design-principles.html). |
| `risk_tier` | yes | `low`, `medium`, or `high`. High needs two approvers. |
| `framework` | yes | `create_agent` (default), `strands`, or `harness`. |
| `deployment` | yes | `docker`. Zip is not a value we build now. |
| `trigger` | yes | `none`, `event`, or `schedule`. |
| `identity.acts_as` | yes | `user` or `service`. |
| `identity.scopes` | yes | Map of tool or knowledge target to allowed scopes. Empty when the pattern calls no external account. |
| `model.primary` | yes | Model or geographic profile id. Not a resource ARN in git. |
| `model.fallback` | yes | Second profile. Empty only when the design page explains why there is no fallback. |
| `model.region_profile` | yes | `eu` unless the design page names another geography. |
| `model.cache` | yes | `off` until the model access layer exists. Later: `auto`. |
| `model.team_tag` | yes | Team tag on the agent, its role, and its logs. |
| `memory.enabled` | yes | `true` or `false`. |
| `memory.write_policy` | yes | `validated` or `off`. `off` is allowed only when `enabled` is false. |
| `memory.namespace` | yes | Default `{agent_version}/{environment}`. |
| `knowledge.enabled` | yes | `true` when the pattern retrieves shared documents. |
| `knowledge.gateway_target` | when enabled | `knowledge-base`. The Gateway target, not a custom search tool. |
| `knowledge.filter_from` | when enabled | `verified-login`. Tenant and role come from the front door, not from the model. |
| `tools.from_registry` | yes | Names already in AWS Agent Registry. The pattern does not copy tool source. |
| `tools.cedar` | yes | Path to the Cedar file for this release. |
| `lifecycle.idle_timeout_s` | yes | Chat default 300 (5 minutes). Background jobs set their own and explain it. Must be <= `max_lifetime_s`. |
| `lifecycle.max_lifetime_s` | yes | Chat default 1800 (30 minutes). MicroVMs cannot exceed 28800. |
| `lifecycle.resumable` | yes | `true` when a checkpoint is required (approval waits and ambient jobs). |
| `lifecycle.max_steps` | yes | Step cap for one job attempt. |
| `lifecycle.timeout_s` | yes | Wall-clock cap for one attempt. |
| `lifecycle.max_retries` | yes | Retry cap for retryable faults. |
| `lifecycle.session_id_min` | yes | 33. The front door rejects anything shorter. |
| `context.token_budget` | yes | Assembly budget. |
| `context.compaction_at` | yes | When to summarize, below the budget. |
| `context.clear_tool_results` | yes | Drop old tool results before summarizing. Default true. |
| `approval.required_for` | yes | Includes `send`, `spend`, `delete`, and `change` whenever the pattern can do that action. |
| `approval.expire_s` | yes | Token lifetime. Expiry fails closed. |
| `approval.reviewers` | yes | 1, or 2 when `risk_tier` is high. |
| `output_schema` | yes | Path to the schema checked before a side effect or a UI render. |
| `runtime.header_allowlist` | yes | Headers forwarded into the session. CDK sends this on every update. Runtime forwards only `Authorization` and `X-Amzn-Bedrock-AgentCore-Runtime-Custom-*`, so it carries the actor header. The session header is not listed: Runtime reads it itself. |
| `runtime.session_header` | yes | `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`, or `Mcp-Session-Id` when the protocol is MCP. |
| `data.classification` | yes | `public`, `internal`, or `confidential`. |
| `data.pii` | yes | Whether personal data can appear. |
| `data.region` | yes | Where prompts, memory, and logs are processed. |
| `data.log_retention_days` | yes | Default 90. |
| `data.audit_retention_days` | yes | At least the log retention. Longer when the pattern has side effects. |
| `eval.golden_set` | yes | Path to `eval/golden_set.json`. |
| `eval.threshold` | yes | Goal-success minimum. The policy pattern uses 0.8 for the session goal and 0.7 for source-backed sentences. |
| `eval.groundedness` | for retrieval | Pass mark 0.7. Every factual sentence must be backed by a source. |
| `eval.runs_per_case` | yes | 1 on the pull-request fixture check. 10 when benchmarking live. |
| `cost.max_usd_per_run` | yes | Cap for one job. |
| `cost.monthly_cap_usd` | yes | Cap for the pattern. Also enforced per user and per team at the front door. |
| `cost.on_cap` | yes | `pause`. The pattern stops starting new jobs. |
| `release.id` | stamped | CI writes it. Authors leave it blank in git. |
| `endpoint` | yes | Named endpoint for this environment. Never `DEFAULT`. |

Example shape for the policy pattern (values are placeholders, not a live config):

```yaml
name: company-policy-qa
owner: team@example.com
autonomy: assistant
risk_tier: low
framework: create_agent
deployment: docker
trigger: none
identity:
  acts_as: user
  scopes: {}
model:
  primary: eu-geographic-profile-id
  fallback: second-eu-profile-id
  region_profile: eu
  cache: off
  team_tag: team-name
memory:
  enabled: false
  write_policy: off
  namespace: "{agent_version}/{environment}"
knowledge:
  enabled: true
  gateway_target: knowledge-base
  filter_from: verified-login
tools:
  from_registry: []
  cedar: policies/tools.cedar
lifecycle:
  idle_timeout_s: 300
  max_lifetime_s: 1800
  resumable: false
  max_steps: 8
  timeout_s: 120
  max_retries: 3
  session_id_min: 33
context:
  token_budget: 120000
  compaction_at: 100000
  clear_tool_results: true
approval:
  required_for: []
  expire_s: 86400
  reviewers: 1
output_schema: schemas/answer.json
runtime:
  header_allowlist:
    - Authorization
    - X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id
  session_header: X-Amzn-Bedrock-AgentCore-Runtime-Session-Id
data:
  classification: internal
  pii: false
  region: eu-west-2
  log_retention_days: 90
  audit_retention_days: 90
eval:
  golden_set: eval/golden_set.json
  threshold: 0.8
  groundedness: 0.7
  runs_per_case: 1
cost:
  max_usd_per_run: 0.50
  monthly_cap_usd: 200
  on_cap: pause
release:
  id: ""
endpoint: DEV
```

`eu-west-2` here is the region name the pattern chooses. It is not an account id. A policy Q&A pattern leaves `approval.required_for` empty because it does not send, spend, delete, or change. Its golden set includes deliberately messy fake policies so a wrong source or a conflict can fail the score. [Eval-first sample](https://github.com/aws-samples/sample-eval-first-building-enterprise-agents-with-agentcore). An ambient pattern sets `trigger: event`, `identity.acts_as: service`, `lifecycle.resumable: true`, a longer lifetime with a written reason, and lists every side effect under `approval.required_for`.

## The twelve-item kit

Every pattern folder contains:

1. `README.md`, including the local Docker prerequisites (`docker ps`, Docker or Finch).
2. `pattern.yaml`, including the memory section and `deployment: docker`. The generator writes `agentcore.json`.
3. Prompt files, not prompts buried only in Python. A harness pattern still keeps the prompt in a file the config points at.
4. A Cedar file that limits tools.
5. Human approval on send, spend, delete, and change, using the pause in this page.
6. Tracing, with the release id on the turn.
7. Unit tests and contract tests.
8. `eval/golden_set.json`. Retrieval patterns include source-backed scoring and goal-success scoring.
9. `events/` with sample events, or an explicit empty reason in the README when `trigger` is `none`. `make local` runs the compose stack against these events.
10. Untrusted-input tags, guardrails, and secrets from Secrets Manager.
11. Step, timeout, and retry limits in `lifecycle`, plus the chat or background session lifetimes.
12. One CDK deploy and a teardown path. The image is ARM64 in ECR. Teardown always runs.

`docs/design.md` follows the pattern outline and is part of the folder even though it is not one of the twelve. A Dockerfile sits next to the agent. It is part of item 12.

## Checks

**Every pull request.** The job runs inside the toolchain container. Ruff, mypy, `pytest -m "not runtime"`, the boundary checker, the in-process judge, an offline check that `golden_set.json` matches the schema, a score of stored trace fixtures, and Trivy on any image the change builds. No deploy.

**Doctor.** A read-only command checks Docker (`docker ps`), the AgentCore CLI, account access, secret names, and model access before a deploy. It changes nothing. [Enterprise platform sample](https://github.com/aws-samples/sample-agentcore-enterprise-platform).

**Verify.** After a deploy, verify re-checks the controls the design promised: front door on the path, identity, Cedar, guardrails, tracing, audit, the header allowlist, the session header, and the golden set. A miss fails the job.

**Production mode.** A deploy aimed at the production endpoint refuses to continue when any required control is missing: verified identity through the front door, Cedar, guardrails, tracing, audit, a kill switch, quotas, the header allowlist, `deployment: docker`, an eval golden set, and approvals when the pattern can send, spend, delete, or change.

**Merge, nightly, and release.** Build each image once on CodeBuild or an ARM64 runner, scan it, deploy to the dev endpoint, run `tests/e2e/` and the live golden set, then tear down. Teardown runs even when the tests fail. Temporary runtimes are deleted. The shared test memory is kept. Block below `eval.threshold`, and below `eval.groundedness` when that field is set. This stage is not in the workflows yet. The current Runtime workflow fails closed when settings are missing. That is a gate, not this deploy loop.

Live traffic later uses sampled online evaluation and an alarm on score drops. [AgentCore Evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations.html) and the [GitHub Actions evaluation write-up](https://aws.amazon.com/blogs/machine-learning/automated-agent-evaluation-with-amazon-bedrock-agentcore-and-github-actions/). Pull-request checks prefer stored fixtures. The managed judge is the deploy-stage score. Exact business checks (ids, amounts, the sentence "I couldn't find this in the policies") use a code evaluator, not a model judge.

## Parked on purpose

These are real, and they are not built in the first three patterns:

- Separate AWS accounts for dev, staging, and prod.
- Prompt caching turned on.
- A shared streaming UI.
- Zip deploy of agents or Lambdas.
- A full multi-tenant product (per-tenant memory isolation beyond the knowledge-base filter, and a tenant admin console).
- A job that watches model retirement. [Model lifecycle](https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle.html).
- Feeding thumbs-down and rejected approvals back into the golden set.

## Sources

Choices above are grounded in the research notes supplied with this change (system-design gaps, the six-repo structure comparison, the caching and testing note, and the later survey of other AgentCore implementations, all 8–9 October 2026) and in these docs:

- [AgentCore CLI](https://github.com/aws/agentcore-cli)
- [AgentCore Runtime sessions](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html)
- [AgentCore lifecycle settings](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html)
- [AgentCore Runtime versioning and endpoints](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html)
- [On-behalf-of token exchange](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/on-behalf-of-token-exchange.html)
- [AWS Agent Registry](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry.html)
- [AgentCore Evaluations](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations.html)
- [Bedrock prompt caching](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html)
- [Cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html)
- [Geographic cross-Region inference](https://docs.aws.amazon.com/bedrock/latest/userguide/geographic-cross-region-inference.html)
- [Bedrock Guardrails sensitive information filters](https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-sensitive-filters.html)
- [Bedrock model lifecycle](https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle.html)
- [Resilience patterns with Amazon Bedrock](https://aws.amazon.com/blogs/machine-learning/implementing-resilience-patterns-with-amazon-bedrock-and-llm-gateway/)
- [Automated agent evaluation with GitHub Actions](https://aws.amazon.com/blogs/machine-learning/automated-agent-evaluation-with-amazon-bedrock-agentcore-and-github-actions/)
- [Agentic AI Lens](https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/agentic-ai-lens.html), [design principles](https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/design-principles.html), [appendix A](https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/appendix-a.html)
- [Prescriptive Guidance, enterprise multi-account agent architecture](https://docs.aws.amazon.com/prescriptive-guidance/latest/agent-ops-maturity-roadmap-for-enterprise-ai/introduction.html)
- [Agent platform sample](https://github.com/aws-samples/sample-agent-platform-with-agentcore)
- [Enterprise platform sample](https://github.com/aws-samples/sample-agentcore-enterprise-platform)
- [Multi-tenancy sample](https://github.com/aws-samples/sample-agentcore-and-multitenancy-blog)
- [Eval-first policy-style agent](https://github.com/aws-samples/sample-eval-first-building-enterprise-agents-with-agentcore)
- [Loom](https://github.com/awslabs/loom)
- [Production notes on sessions, headers, and the memory quota](https://vindler.solutions/blog/aws-bedrock-agentcore-production-guide)
- [Code Interpreter network isolation](https://unit42.paloaltonetworks.com/bypass-of-aws-sandbox-network-isolation-mode/)
- [Anthropic, Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)
- [Anthropic, Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
- [OWASP LLM05 Improper Output Handling](https://owasp.org/www-project-top-10-for-large-language-model-applications/2_0_vulns/LLM05_ImproperOutputHandling)

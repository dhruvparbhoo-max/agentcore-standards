# Engineering standards for AI agents on AWS Bedrock AgentCore

Team design for coding agents and humans building on AgentCore. Grounded in verification-first agent engineering (Lauren Tan / pstack method) and AgentCore primitives (Runtime, Memory, Gateway, Identity, Observability, Policy).

**Status:** design draft (open decisions 1–4 resolved) — implement as a versioned Python monorepo (or package set) reviewed like production code.  
**Non-goals:** copying team-specific bans from other codebases; auto-merge without independent runtime verdicts; treating CI green as “done.”

---

## 1. Top engineering standards

### 1.1 Verification-first (the trust bar)

Every capability ships with an **eval** that:

1. Invokes the **real AgentCore Runtime** (not a mocked loop for the happy path).
2. Captures **before/after evidence** (structured logs, OTEL spans, Memory events where relevant, tool call records).
3. Asserts an **observable outcome** the user/system cares about (session state, tool side-effect idempotency, guardrail block, cost envelope).

**“It compiles” is not done.** Unit tests of helpers are fine; they do not replace a Runtime eval.

**Done means:** an independent check (different process / agent than the author) can re-run the eval and get a PASS / PASS+NOTES / FAIL verdict with evidence artifacts retained.

### 1.2 Atomic PRs

- One explainable, reviewable, revertible change per PR.
- Prefer short diffs + a **verdict** in the PR body: what was proven, how (eval name + evidence path), what was *not* proven.
- No hard LOC cap; ban mega-PRs that cannot be bisected.
- Stack related work as contiguous verified PRs from a known-good root — do not land the tip of a stack if a lower PR lacks a Runtime verdict.

### 1.3 Encode misses as regression, not reminders

When an agent (or human) skips a read, invents a root cause, or violates a boundary:

1. Reproduce once.
2. Add a **failing eval** or **CI gate** that catches that class of miss.
3. Only then fix the code/skill.

Do not leave “be careful” comments or soft style-guide notes as the only control. Soft skills/Bugbot are layer 3+; hard gates and architecture are the foundation.

### 1.4 Observability from day one

Every agent template ships with:

| Signal | Requirement |
|--------|-------------|
| Tracing | OpenTelemetry through model, tool, Gateway, Memory, Identity, policy evaluation — one correlated trace per turn |
| Structured logs | JSON logs with `runtimeSessionId`, `actorId`, `agentVersion`, `requestId`, tool name, latency, error class |
| Cost tracking | Token / model / tool invocation cost attributes on spans; per-session and per-eval budgets asserted in CI where practical |
| Evidence retention | Eval runs upload traces + logs + Memory snapshots (redacted) as PR artifacts |

If you cannot answer “what did the agent do and why did it cost X?” from telemetry alone, the capability is not production-ready.

### 1.5 Security defaults

- **Least-privilege IAM** for Runtime, Gateway targets, Memory, and any AWS APIs tools touch. Separate roles per agent / environment.
- **No secrets in prompts, Memory payloads, logs, or eval fixtures.** Secrets via IAM / Secrets Manager / Parameter Store; never pasted into system prompts.
- **Input and output sanitization** via Bedrock Guardrails (and Gateway Policy / Cedar where tools are involved) *before* Memory write and *before* user-visible output.
- **Session isolation:** one `runtimeSessionId` per conversation/user boundary; never reuse sessions across tenants.
- **Ephemeral Runtime ≠ durable store:** treat microVM filesystem as scratch; durable facts go through Memory with guardrail-filtered events only.
- **Tool policy:** Gateway fronting tools; deny by default; allowlist tools per agent version.

### 1.6 Idempotent tools + explicit retry semantics

Agents retry. Tools must assume at-least-once delivery.

For every tool:

- Document **idempotency key** (or natural key) and behavior on duplicate calls.
- Prefer put-if-absent / upsert with version checks over fire-and-forget creates.
- Return structured errors: `retryable` vs `fatal`, with backoff hints.
- Evals must include a **double-invoke** case proving no duplicate side effects.

### 1.7 Operating rules for coding agents on this codebase

- Reproduce on real Runtime before claiming a fix.
- Never declare done from compile/unit tests alone.
- Never merge or force-push without an explicit human (unless a later, separately approved auto-merge policy with independent surface verdicts is adopted).
- Never clone repos onto developer machines/box for non-trivial work when cloud agents are available — use Cursor cloud agents against the repo.
- Recurring misses → skill, lint, or CI gate — not another chat reminder.

---

## 2. Primitive catalog

Each primitive is a **tested, versioned, importable Python module** under `packages/`. No copy-paste starters that drift. Language is **Python only** (resolved).

Suggested package layout:

```
packages/
  agentcore-session/      # Runtime session lifecycle
  agentcore-tools/        # Tool registry + Gateway wiring
  agentcore-memory/       # STM/LTM adapters + guardrail hooks
  agentcore-guardrails/   # Bedrock Guardrails + policy helpers
  agentcore-tracing/      # OTEL + cost attributes
  agentcore-eval/         # Eval harness, verdicts, evidence upload
templates/
  minimal-agent/
  agent-with-tools/
  agent-with-memory/
  multi-agent/
  human-in-the-loop/
```

### 2.1 Session management (`agentcore-session`)

**Owns:** create/reuse `runtimeSessionId`, sticky routing headers, idle/TTL policy, clean termination, cold-start metrics.

**API sketch:**

- `Session.start(actorId, agentVersion) -> SessionHandle`
- `Session.invoke(input, *, sessionId?) -> InvokeResult`
- `Session.command(sessionId, shellCommand) -> CommandResult` (when using Runtime command path)
- `Session.end(sessionId)`

**Invariants:**

- One session = one tenant conversation boundary.
- No durable user state left only on the microVM disk.
- Session IDs never logged next to PII without redaction policy.

**Required tests:** sticky session reuse; new session after terminate; cross-tenant isolation smoke; latency cold vs warm.

### 2.2 Tool registry (`agentcore-tools`)

**Owns:** registering tools, Gateway target mapping, Cedar/IAM policy attachments, schema validation, idempotency wrappers.

**API sketch:**

- `@tool(name, schema, idempotent=True)` registration
- `ToolRegistry.bind_gateway(gatewayId)`
- `invoke_tool(name, args, *, idempotencyKey)` with retry classification

**Invariants:**

- Tools are deny-by-default until Gateway policy allows.
- Side-effecting tools require an idempotency strategy or fail CI.
- Tool schemas are versioned; breaking schema changes bump major.

**Required tests:** allow/deny policy; double-invoke idempotency; schema rejection; timeout/retryable error paths.

### 2.3 Memory wiring (`agentcore-memory`)

**Owns:** short-term events vs long-term records, `actorId` / namespace isolation, retrieve/create hooks, guardrail filter *before* write.

**API sketch:**

- `MemoryClient.create_event(session, role, content)` — rejects if guardrail fails
- `MemoryClient.retrieve(actorId, query, *, namespace)`
- `MemoryClient.list_session_events(sessionId)`

**Invariants:**

- Never store raw unguarded model or user text.
- Namespaces scoped per agent + environment.
- Retrieval results tagged with provenance for traces.

**Required tests:** guardrail block prevents write; cross-actor isolation; STM vs LTM separation; retrieve relevance smoke eval.

### 2.4 Guardrails (`agentcore-guardrails`)

**Owns:** Bedrock Guardrails config as code, input/output filters, Memory write gate, optional Gateway policy helpers.

**API sketch:**

- `Guard.apply_input(text) -> Sanitized | Blocked`
- `Guard.apply_output(text) -> Sanitized | Blocked`
- `Guard.allow_memory_write(event) -> bool`

**Invariants:**

- Guardrail IDs/versions pinned in config; changes are PRs with eval diffs.
- Blocked content never reaches Memory or user channel.

**Required tests:** known attack/PII fixtures; version pin drift detection; Memory write denial path.

### 2.5 Tracing (`agentcore-tracing`)

**Owns:** OTEL setup for AgentCore, span naming conventions, cost attributes, evidence exporters for evals.

**Conventions:**

- Root span per user turn: `agent.turn`
- Children: `model.invoke`, `tool.<name>`, `memory.write|retrieve`, `gateway.call`, `guardrail.check`
- Attributes: `agent.version`, `runtime.session_id` (hashed if needed), `cost.tokens`, `cost.usd_estimate`

**Required tests:** span tree shape on golden path; missing-cost attribute fails CI for production templates.

### 2.6 Eval harness (`agentcore-eval`) — shared by all templates

**Owns:** task + rubric definition, Runtime-boundary runner, PASS / PASS+NOTES / FAIL verdict, evidence bundle, multi-model matrix hook.

**Harness-agnostic (resolved):** primitives and evals sit at the **AgentCore Runtime boundary** via the `bedrock-agentcore` SDK. Swapping AgentCore Harness vs BYO container later means **re-wrapping the entrypoint only** — not rewriting evals or primitives.

The eval harness exposes a thin interface; each product harness implements it:

- `start(...)` — provision / bind Runtime session
- `invoke(...)` — send a turn
- `capture_traces(...)` — collect OTEL / logs / cost evidence
- `tear_down(...)` — end session, sanitize handles

**API sketch:**

- `Eval(name, setup, act, assert_, rubric)`
- `run_eval(eval, *, agentVersion, harness: RuntimeHarness) -> Verdict`
- `run_suite(path) -> Report`

**Rules:**

- Blinded dirs where possible (no `*eval*` hints that change agent behavior).
- Author agent ≠ judge agent for ship gates (independent surface verdict).
- Evidence retained as CI artifacts.
- Evals run in the **same AWS account as dev** (resolved) — use stage isolation via agent versions / namespaces / IAM paths, not a separate account.

### 2.7 Hill-climbing (harness improvement loop)

Once Runtime and tracing are hooked up, a harness change follows the rhythm in [docs/evals/hill-climbing.md](evals/hill-climbing.md). It is adapted from LangChain's Better Harness recipe: source and tag cases, split each topic into an optimization set and a holdout set, record a baseline, make one harness change, validate regressions, human review, then promote or prune. Production traces feed the next cases.

`uv run python -m agentcore_eval.hillclimb steps` prints that command sequence. `compare` diffs two evidence directories and blocks when a previously passing case fails or a case disappears. That diff is a structure check. It is not an independent Runtime verdict, and writing the rhythm down is not a claim that a production climb has been run. The ship gate stays §4.2.7.

---

## 3. Starter templates

Each template is a **runnable AgentCore agent** plus a **attached eval suite**. Promoting a template means its suite is green on real Runtime in CI.

### 3.1 Minimal working agent

- Entrypoint via AgentCore Harness *or* BYO container — both implement the same RuntimeHarness interface; body uses session primitive + single model invoke.
- Session primitive only; no tools, no Memory.
- **Evals:** cold start invoke; sticky multi-turn session; structured log + trace present; cost attributes present.

### 3.2 Agent-with-tools

- Minimal + Tool registry + Gateway allowlist (1–2 demo tools, one of them side-effecting with idempotency key).
- **Evals:** successful tool path; policy deny path; double-invoke idempotency; tool error classified retryable vs fatal.

### 3.3 Agent-with-memory

- Minimal + Memory + Guardrails on write path.
- **Evals:** multi-turn recall across invoke; guardrail blocks bad write; cross-actor isolation; retrieve after session recycle (LTM path if enabled).

### 3.4 Multi-agent orchestration

- Coordinator agent + 1–2 specialist agents (separate Runtime versions or logical agents sharing Gateway/Memory namespaces carefully).
- Explicit handoff protocol (structured messages, not free-form hope).
- **Evals:** handoff produces required specialist side-effect; no cross-namespace Memory leak; trace shows parent/child linkage; cost roll-up across agents.

### 3.5 Human-in-the-loop

- Agent pauses on high-risk tools (payments, destructive writes, IAM changes) awaiting approval token.
- Approval channel pluggable (console, Slack, API).
- **Evals:** blocked without approval; proceeds only with valid approval; approval expiry; audit log of who approved.

---

## 4. Versioning and review (so sloppy primitives cannot become defaults)

### 4.1 Versioning

- SemVer on every `packages/*` module and every template.
- AgentCore Runtime **agent versions** map 1:1 to a git tag / release of the template + pinned primitive versions (lockfile).
- Breaking changes to tool schemas, Memory namespaces, or Guardrail pins = **major** bump + migration note.
- Templates depend on packages via range pins reviewed in CODEOWNERS; no “just copy the folder.”

### 4.2 Review gates (merge requirements)

A PR that touches a primitive or template must include:

1. **Atomic scope** + short diff + verdict section.
2. **New/updated Runtime eval** for the behavior change (or explicit waiver with expiry — rare).
3. **Green `agentcore-eval` suite** in CI against a real AgentCore test account/stage.
4. **Telemetry check:** required spans/attributes present.
5. **Security checklist:** IAM diff reviewed; no secrets in prompts/fixtures; Guardrail pin change called out.
6. **Idempotency:** any new side-effecting tool has double-invoke coverage.
7. **Ship / auto-merge (resolved):** CI green alone is **not** a merge verdict. Auto-merge is allowed **only after an independent surface verdict** (a different agent/process than the author exercises the real Runtime path → PASS / PASS+NOTES). No additional human approval on top of that Lauren gate. FAIL or missing evidence blocks merge.

CODEOWNERS: `packages/**` requires platform/agents owners; template majors require the same.

### 4.3 Promotion path: experiment → default

| Stage | Rule |
|-------|------|
| `experiments/` | Allowed to be messy; cannot be imported by `templates/` |
| `packages/` candidate | Behind feature flag; eval suite must exist |
| Default template dependency | Only after N green CI days + owner approval + changelog |
| Deprecation | Soft-remove with major bump; CI fails new imports of deprecated APIs |

A sloppy experiment **cannot** become a starter default without crossing these gates. Copy-paste from `experiments/` into `templates/` is blocked by lint/CI path rules.

### 4.4 Coding-agent workflow on this repo

1. Cloud agent opens a branch for one atomic change.
2. Implements against primitives (no fork-and-edit of template guts unless the PR *is* the primitive change).
3. Runs / extends the template’s eval suite on AgentCore Runtime.
4. Opens PR with evidence links and verdict.
5. Independent surface verdict (Lauren gate) → auto-merge when PASS / PASS+NOTES; no extra human approval required on top. FAIL or missing evidence blocks merge.

---

## 5. Suggested first 30 days

1. Scaffold monorepo + `agentcore-tracing` + `agentcore-eval` + minimal template with one green Runtime eval.
2. Add `agentcore-session` + sticky-session evals.
3. Add `agentcore-tools` + Gateway deny/allow + idempotent tool eval.
4. Add `agentcore-memory` + `agentcore-guardrails` with write-gate evals.
5. Publish agent-with-tools and agent-with-memory templates as v0.1 defaults.
6. Multi-agent + HITL after the above are boringly green.

---

## 6. Mapping Lauren’s method → AgentCore

| Lauren / pstack idea | AgentCore encoding |
|----------------------|--------------------|
| Verify on the real surface | Evals call real Runtime / Memory / Gateway |
| Feature map | Template README + “capability map” (entrypoints, tools, Memory namespaces, approval gates) |
| Skills for repeated misses | Repo skills + failing evals that encode the miss |
| Shortest path = correct path | Importable primitives + CI bans on copy-paste / forbidden imports |
| Soft rules → hard gates | Guardrails, Cedar/IAM, eval CI, CODEOWNERS |
| Independent ship verdict | Separate eval runner / judge; CI green alone ≠ merge; auto-merge only on independent PASS / PASS+NOTES |
| Hill-climb a harness | Tagged optimization/holdout sets, one change, regression diff, human review; the climb diff does not replace the Runtime verdict |

---

## 7. Decisions

### Resolved

1. **Language:** Python.
2. **Harness strategy:** Harness-agnostic. Primitives and evals stay at the AgentCore Runtime boundary via the `bedrock-agentcore` SDK. Swapping harnesses later only means re-wrapping the entrypoint. The eval harness exposes a thin interface (`start`, `invoke`, `capture_traces`, `tear_down`); each product harness implements it.
3. **Eval AWS account:** Same AWS account as dev (isolate with stages / agent versions / namespaces / IAM paths — not a separate account).
4. **Auto-merge:** Follows Lauren’s gate — only after an **independent surface verdict**, not CI green alone. No additional human approval on top of that gate.

### Still open

5. Memory connector via Gateway for all writes, or direct Memory SDK for STM only?

---

## 8. Parallel agent operating model

Fearless parallelism only after one agent can complete a full loop (implement → Runtime eval → evidence → independent verdict). Until that local verify path is green, parallelize **read/scout** work only — not writers. Matches Lauren / pstack: go deep before broad; separate writers; prove on the real surface; encode misses as gates/skills.

### 8.1 Roles

| Role | Who | Owns | Must not |
|------|-----|------|----------|
| **Coordinator bot** | Standing agentcore bot (human-proximate) | Task queue, ownership leases, stack order, spawn/watch cloud agents, refuse colliding paths, trigger judge after author PR is ready, decide land vs rework | Implement package code itself on shared branches; merge without an independent Runtime verdict |
| **Cloud coding agent** | One Cursor cloud agent per leased path | One atomic PR on its owned path(s); extend evals for that change; attach evidence + author verdict draft in PR body | Touch another agent’s leased path; declare done from unit tests/CI green alone; force-push shared `main` |
| **Judge / eval agent** | Separate process/agent from the author | Re-run the claimed Runtime eval(s) via `agentcore-eval` harness (`start` / `invoke` / `capture_traces` / `tear_down`); emit PASS / PASS+NOTES / FAIL with evidence artifacts | Share author context that biases the rubric; edit product code to make the eval pass |
| **Scout** | Read-only cloud agent or subagent | Capability maps, `/how`-style traces, dependency/blast-radius notes, open-decision research (e.g. Memory-via-Gateway), miss → skill candidates | Open write PRs; hold package ownership leases |

**Independence rule:** author agent ≠ judge agent for ship gates (§1.1, §4.2.7). Auto-merge only on independent PASS / PASS+NOTES. No extra human approval on top of that gate.

### 8.2 Work breakdown (fan-out without merge collisions)

Partition by **ownership path**, not by “feature story.” Stories that span packages become a **stack of atomic PRs**, each with one owner path.

| Lane | Primary path(s) | Typical atomic PR | Depends on (stack below) |
|------|-----------------|-------------------|---------------------------|
| A — Foundation | `packages/agentcore-tracing`, `packages/agentcore-eval` | OTEL conventions + thin RuntimeHarness + one golden Runtime eval | — (root of every stack) |
| B — Session | `packages/agentcore-session` | Session lifecycle + sticky/cold evals | A |
| C — Tools | `packages/agentcore-tools` | Registry + Gateway allow/deny + idempotency wrapper | A (and B if session-bound invoke helpers) |
| D — Guardrails | `packages/agentcore-guardrails` | Guard apply_input/output + pin config | A |
| E — Memory | `packages/agentcore-memory` | STM/LTM adapters + write-gate hook | A + D (guard before write) |
| F — Templates | `templates/<name>/` only | Wire pinned primitives; template-local eval suite | Matching primitive lanes green |
| G — Meta | `docs/`, `skills/`, capability maps, CI path bans | Encode a miss; no product API change | May run parallel to A–F as scout+doc PRs |

**Fan-out rules:**

1. **One lease per path prefix** under `packages/<name>/` or `templates/<name>/`. Coordinator records lease → agent → branch → PR.
2. **Shared interfaces land first.** Public API sketches in DESIGN §2 freeze (or PR) before two consumers diverge. Prefer a tiny “types/protocol” commit in lane A over dual edits.
3. **Templates never invent primitives.** Template agents import packages; if they need a new API, they file a blocker and the coordinator spawns/queues a package PR — they do not fork package guts into the template.
4. **Eval ownership:** behavior change PR owns the new/updated eval under `packages/agentcore-eval` *or* the template’s suite for that behavior. Two agents must not edit the same eval file; split suites by package (`evals/session/`, `evals/tools/`, …).
5. **Collisions → serialize.** If two tasks need `packages/agentcore-tools`, second waits or re-scopes to a non-overlapping subpath explicitly leased (e.g. `.../idempotency/` vs `.../gateway/`) — default is **one agent per package**.

### 8.3 Branching / ownership rules

- **Branch naming:** `agent/<role-or-id>/<package-or-template>/<short-slug>` (example: `agent/c7/agentcore-session/sticky-reuse`).
- **One owner path per PR.** Allowed: one package *or* one template. Disallowed: `agentcore-memory` + `agentcore-guardrails` in the same PR unless the PR is explicitly the wiring spike and both paths are leased to the same agent (rare; prefer stack).
- **No two agents on the same package** (or same template dir) concurrently. Scout may read anything; writers need a lease.
- **Worktrees / isolated checkouts** for every cloud agent (pstack: separate writers, no shared dirty tree).
- **Rebase etiquette:** rebase only onto known-good `main` or onto the **immediate parent** in a declared stack. Do not rebase mid-stack tips onto each other without coordinator acknowledgment.
- **CODEOWNERS** still apply; independence gate is additional, not a substitute.

### 8.4 Stack of atomic PRs + independent Runtime verdict before land

```
main (known-good)
  └─ PR1 tracing+eval harness interface     [judge PASS] → land
       └─ PR2 session                         [judge PASS] → land
            ├─ PR3a tools                     [judge PASS] → land
            └─ PR3b guardrails                [judge PASS] → land  (parallel OK: different packages)
                 └─ PR4 memory                [judge PASS] → land
                      └─ PR5 template X       [judge PASS] → land
```

**Land rules:**

1. Each PR is atomic, revertible, and carries a **verdict section**: what was proven, eval name(s), evidence path/artifact, what was *not* proven.
2. CI green is necessary but **not** sufficient (§4.2.7).
3. Coordinator requests a **judge agent** only after author marks ready; judge re-runs Runtime evals in the **same AWS account as dev** (stage/namespace/IAM isolation).
4. **Auto-merge** on PASS / PASS+NOTES with retained evidence. FAIL or missing evidence blocks merge; author reworks on the same lease.
5. **Never land a stack tip** if a lower PR lacks an independent Runtime verdict. Contiguous verified prefix only.
6. PASS+NOTES: land allowed; notes become a queued follow-up issue or skill — not a silent waiver.

### 8.5 Shared knowledge (living, not chat lore)

| Artifact | Purpose | Updated when |
|----------|---------|--------------|
| `DESIGN.md` (this doc) | Normative standards, primitives, gates, parallel model | Decisions resolve; operating rules change |
| **Capability maps** per template/package | Entrypoints, tools, Memory namespaces, Gateway targets, approval gates, how to drive + what observable proves success (Lauren feature-map analogue for Runtime) | New template behavior or eval surface |
| **Skills** under repo skills/ | Recurring misses (skipped Runtime verify, invented root cause, cross-package edit, secrets in fixtures, non-idempotent tool) | After reproduce → failing eval/CI gate → then skill |
| Eval evidence bundles | Traces, logs, Memory snapshots (redacted), cost attrs | Every judge run |
| Decision log (optional TSV per autopilot) | Phase / decision / evidence / result for overnight stacks | Long orchestrated runs |

Shortest path = correct path: import primitives; CI bans copy-paste from `experiments/` into `templates/`; soft reminders are not controls.

### 8.6 When NOT to parallelize

Do **not** spawn multiple writing cloud agents until:

1. **Lane A is boringly green:** `agentcore-tracing` + `agentcore-eval` + minimal template have at least one independent PASS on real Runtime.
2. Local/cloud **verify path** is documented (how to `start` → `invoke` → `capture_traces` → `tear_down` and where evidence lands).
3. Coordinator can grant/revoke path leases and detect collisions.
4. Judge path exists as a separate agent/process (even if manually triggered at first).

Until then: one coding agent + optional scouts. Parallelizing writers before the verify path works multiplies confident wrong merges.

Also do not parallelize when: the task is a single-package spike; public API is still thrashing; or two “independent” stories share an unreleased interface — serialize or land the interface first.

### 8.7 First parallel wave (concrete)

**Prerequisite:** finish sequential bootstrap per §5 step 1 (scaffold + tracing + eval + minimal template, one green Runtime eval + one independent judge PASS).

**Wave 1 — spawn exactly three agents:**

| Agent | Lease | Atomic goal | Done means |
|-------|-------|-------------|------------|
| **Coder-1** | `packages/agentcore-session` | Session.start/invoke/end + sticky reuse + cold-start metrics hooks | Runtime evals for sticky reuse + terminate-then-new; traces show session attrs; judge PASS |
| **Coder-2** | `packages/agentcore-tools` | Tool registry + Gateway bind + one idempotent side-effecting demo tool | Allow/deny + double-invoke evals green; judge PASS |
| **Scout-1** | read-only | Capability map for `templates/minimal-agent`; draft maps for tools/memory templates; list blast radius if session↔tools shared types needed | Written maps + gap list; **no** write PR (or docs-only PR under `docs/capability-maps/`) |

**Hold back:** memory + guardrails (need guard-before-write order); templates beyond minimal (wait for session/tools PASS); multi-agent/HITL.

**Wave 2 (after Wave 1 lands):** Coder on `agentcore-guardrails`, then `agentcore-memory` (stack, not parallel with each other unless interfaces frozen); parallel template agents for `agent-with-tools` and `agent-with-memory` only after their primitive deps are on `main` with judge PASS.

**Coordinator checklist before each spawn:** lease free? parent stack verdict present? eval suite path non-overlapping? judge booked for ready PRs?

### 8.8 Coordinator spawn prompt (template)

```
You are the agentcore coordinator. Read DESIGN.md (esp. §§1, 4, 8). Goal: <GOAL>.

Rules:
- Lease exactly one ownership path per agent (packages/<name> OR templates/<name>). Never two writers on the same package/template.
- Each agent: one atomic PR, isolated worktree/branch agent/<id>/<path>/<slug>, implement + extend Runtime evals at the bedrock-agentcore boundary (harness: start/invoke/capture_traces/tear_down). Author ≠ merge authority.
- Done for an author = PR with verdict section + evidence paths. Land only after a SEPARATE judge agent re-runs the Runtime evals → PASS or PASS+NOTES. CI green alone is not enough. No extra human approval beyond that gate.
- Evals in the same AWS account as dev (stage/namespace/IAM isolation). Python only. No secrets in prompts/fixtures/Memory.
- If blocked on another package API: stop and report blocker; do not edit outside your lease.
- Encode misses as failing evals/CI/skills, not chat reminders.

Spawn N=<N> agents with these leases and briefs:
1) <AGENT_ID> → lease <PATH> → <ATOMIC_BRIEF> → done means <EVAL_NAMES + observable outcomes>
2) …
N) …

After authors mark ready: spawn judge(s) with blinded rubric, no author chat context. Auto-merge contiguous stack prefix with independent PASS/PASS+NOTES only; never land a tip over an unverified base. Return: leases, PR URLs, verdicts, evidence locs, blockers.
```

---

*End of design draft.*


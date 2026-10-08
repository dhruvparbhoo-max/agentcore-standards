# Staff review — agentcore-standards

**Date:** 2026-10-02
**Reviewer stance:** principal / staff, code quality and style. No product code changed.
**Tree:** `main` at `88bd49d` (through PR #5). Drafts compared in git, not merged.

| Draft | Head | Fork point | What it adds |
| --- | --- | --- | --- |
| [#6](https://cursor.com/codebase/dhruvparbhoo/agentcore-standards/pull/6) invoice desk | `8c22732` | `ace165c` (scaffold, before PRs #1–#5) | `templates/langchain-create-agent` |
| [#7](https://cursor.com/codebase/dhruvparbhoo/agentcore-standards/pull/7) billing supervisor | `6de3b16` | stacked on #6 | `templates/deepagents-agentcore` |
| [#8](https://cursor.com/codebase/dhruvparbhoo/agentcore-standards/pull/8) skills distill | `970f19d` | `88bd49d` (current `main`) | docs + four checklist skills |
| [#9](https://cursor.com/codebase/dhruvparbhoo/agentcore-standards/pull/9) CDK | `2bbe2c4` | `88bd49d` | `infra/` + OIDC deploy |

This environment has no `uv`, so the suite was read and not re-executed here. The findings below are from the source, the tests, and the draft diffs.

## Overall grade

**B+.** Copy the lease, the `RuntimeHarness` protocol, and the habit of labeling stubs. Do not copy this tree as a production AgentCore starter: the golden eval cannot pass on the service client, and the open drafts either predate `agentcore-tools` or stand up Memory ahead of guardrails.

## Strengths

- **The two harnesses are named apart.** `BedrockAgentCoreApp` is the hosted process. `RuntimeHarness` is the eval client (`start` / `invoke` / `capture_traces` / `tear_down`). README, `AGENTS.md`, and `primitives/eval/src/agentcore_eval/__init__.py` say this the same way. That split is the part worth stealing.
- **Stubs say they are stubs.** `primitives/session/README.md`, `agentcore-guardrails`, `agentcore-memory`, and the four template READMEs under `templates/` refuse implementation and name the lease. The root README matches that.
- **Boundaries are a script, not a paragraph.** `scripts/check_boundaries.py` fails the build on `experiments` imports, a 6-line copy of package source into a template, and committed ARN / private-key shapes. The ARN regex is split in source so the scanner does not flag itself. CI runs it (`.github/workflows/ci.yml`).
- **Workspace deps are explicit.** Root and `templates/minimal-agent` both declare `agentcore-tracing` and `agentcore-eval`. Templates are `package = false`. Hatchling packages stay under `primitives/`.
- **Tool errors are operational.** `ToolResult` is either output or a classified error. Retryable carries `backoff_ms`; fatal does not (`primitives/tools/src/agentcore_tools/errors.py`). Schema failures name the path and omit the rejected value (`schema.py`). Deny-by-default is the empty `Policy`, and a forbid wins (`policy.py`). The demo handler is put-if-absent on `record_id` (`demo.py`).
- **The judge vocabulary is honest on the mock path.** `evidence/judge/verdict.json` can say `SKIPPED` with `missing_settings`. `docs/eval-pass-path.md` says that exit 0 on `SKIPPED` is still a blocked merge. The in-process golden eval checks a real entrypoint (`templates/minimal-agent/src/minimal_agent/entrypoint.py`), a hashed session id on the span, parent/child span shape, and two structured logs (`templates/minimal-agent/evals/golden_turn.py`).
- **Prose is consistent.** Docstrings say what the function does. Design, READMEs, and module text share one register. There is little decorative abstraction.

## Critical issues

### 1. The golden eval cannot pass on `AgentCoreRuntimeHarness`

`templates/minimal-agent/evals/golden_turn.py` requires two structured logs whose `runtimeSessionId` equals the raw session id and whose `actorId` equals `actor-golden`. `AgentCoreRuntimeHarness.capture_traces` always returns `logs=()`:

```155:161:primitives/eval/src/agentcore_eval/runtime_client.py
    def capture_traces(self, session: SessionHandle) -> TraceBundle:
        state = self._require_known(session)
        if self._span_collector is None:
            return TraceBundle(session_id=session.session_id, spans=(), logs=())
        raw = self._span_collector.collect(session.session_id, state.started_at, datetime.now(UTC))
        spans = tuple(_span_from_mapping(item) for item in raw)
        return TraceBundle(session_id=session.session_id, spans=spans, logs=())
```

`invoke` sends `agentRuntimeArn`, the JSON payload, `runtimeSessionId`, and an optional qualifier. It does not send `x-agentcore-actor-id`. The entrypoint reads the actor only from that header and otherwise stores `"unknown"` (`templates/minimal-agent/src/minimal_agent/entrypoint.py`).

`start` and `tear_down` only flip a local flag. They do not create or end a Runtime session. A second `invoke` after `tear_down` fails in this process. The microVM session is untouched.

`primitives/eval/tests/test_harness.py` checks the boto call shape against a fake collector. It does not run `minimal-agent.golden-turn`. `templates/minimal-agent/tests/test_golden_eval.py` would call the real suite when credentials exist, and that suite fails on the empty log list before it ever looks at CloudWatch span shape.

`docs/eval-pass-path.md` still describes this command as the real Runtime PASS path. With credentials set, the honest result is `FAIL`. Without them, the result is `SKIPPED` and process exit 0.

### 2. The ship-shaped CI jobs go green when the real surface is absent

`.github/workflows/runtime-evals.yml` prints a skip line and `exit 0` when `AWS_ACCESS_KEY_ID`, `AWS_REGION`, `AGENTCORE_RUNTIME_ARN`, or `AGENTCORE_SPAN_LOG_GROUP` is empty. It never writes `verdict.json`. It runs `pytest -m runtime`, not `python -m minimal_agent.judge --harness runtime`. `AGENTS.md` calls that workflow "the same gate" as the judge.

`primitives/eval/src/agentcore_eval/judge.py` puts `"SKIPPED"` in `PASS_STATUSES`, so the judge process also exits 0. The JSON status is the word `SKIPPED`, which is the right word. The GitHub check is still success. DESIGN §4.2.7 says missing evidence blocks merge. An agent that copies this workflow will treat a green check as the Lauren gate.

`AgentCoreRuntimeHarness.from_env` only requires the runtime id and the region. `missing_runtime_settings` also requires `AWS_ACCESS_KEY_ID` and `AGENTCORE_SPAN_LOG_GROUP`. A role-based environment and the skip gate disagree about what "configured" means.

### 3. The operating rule was already broken on `main`

`AGENTS.md` says lane B/C/D wait for an independent Runtime PASS, and that a stack tip does not land over an unverified base. `main` already contains `agentcore-tools` (PR #2) and the offline eval pack (PR #3) with no such PASS. The READMEs admit the gap. The lease table still says tools are "implemented" and the next-agent section still says not to start that writer. Agents will copy the landed exception.

The eval pack makes the same move inside `agentcore-eval`: `PatternGuard`, `BusinessStub`, `LexicalGroundednessScorer`, and `InMemoryHitlGate` stand in for packages that are still README stubs. The docs in `docs/evals/README.md` say so. The public `agentcore_eval` exports still look like the product API (`GuardrailCheck`, `HitlGate`, `business_harness`).

## Important improvements

### Session id field means two things

Spans store `hash_session_id` (`primitives/tracing/src/agentcore_tracing/turn.py`). The minimal-agent log stores the raw id, and the golden eval requires that. `ToolRegistry._log` writes the **hash** into the same JSON key `runtimeSessionId` (`primitives/tools/src/agentcore_tools/registry.py`). A consumer cannot tell which one it has. DESIGN §2.1 wants session ids kept off PII. The template log line carries the raw session id next to `actorId`.

### Idempotency is two mechanisms, and the wrapper is racy

`IdempotencyStore.lookup` and `remember` are separate critical sections (`idempotency.py`). Two overlapping `invoke_tool` calls with one key both miss, both run the handler, and the first `remember` wins. `remember` skips retryable errors, so a timeout is not cached.

`_execute` starts a `ThreadPoolExecutor` per call and returns `retryable` on `TimeoutError`, then `shutdown(wait=False, cancel_futures=True)`. `cancel_futures` does not stop the thread that is already inside the handler. That handler can still commit after the caller has been told to retry.

`dispatch_target` and `make_lambda_handler` skip the idempotency key on purpose. The Lambda comment says the natural key inside the tool is the durable guard. That is true for `put_record`. It is a comment for every other side-effecting tool. `AgentCoreGatewayClient.sync` treats `ConflictException` as `{"status": "EXISTS"}` and does not compare the live target to the schema (`runtime_client.py` in tools). A drifted Gateway target stays "synced".

Cedar statements omit the agent version (`policy.py`). The README says to keep one policy engine per version. Nothing in `sync` checks that.

### Naming and public surface

`InMemoryRuntimeHarness` lives in `primitives/eval/src/agentcore_eval/in_memory.py`. The product Memory package is the stub at `primitives/memory/`. The file name will be copied as the memory client.

`agentcore_tools.__init__` exports `DemoTools`, `RecordStore`, `PUT_RECORD`, `LAMBDA_TARGET`, and `write_double_invoke_evidence`. The demo is the sample, and it is also the library root. Callers will import the fixture.

`estimate_turn_cost` is `max(1, len(text) // 4)` and a default of `$0` (`primitives/tracing/src/agentcore_tracing/cost.py`). The golden eval requires `cost.tokens >= 1`, which any non-empty prompt satisfies. The module comment is honest that this is not a billing export. The eval still treats those attributes as the DESIGN §1.4 cost check. A copied template will ship the heuristic as "cost tracking".

### Eval pack proves the fixture agrees with itself

`PatternGuard` blocks the substring `ignore previous instructions` and the marker `BLOCK-PII`, and allows a memory write only when `event["guarded"] is True` (`guardrails.py`). `BusinessStub` deletes `actor_id` (`stub_agent.py`). `LexicalGroundednessScorer` is a substring check. These are useful shapes for a later package. They are not Bedrock Guardrails, Gateway policy, or a faithfulness evaluator. `OnDemandEvaluatorsAdapter` is optional and does not produce a `Verdict`.

`write_evidence` rejects any bundle whose JSON contains the marker `"arn:" + "aws:"` (`harness.py` `assert_no_resource_arn`). A real span that records a function id or a runtime id crashes the suite with `HarnessError` instead of a `FAIL` verdict. The runner does not catch that write.

Log capture in `InMemoryRuntimeHarness` attaches a handler to the process-wide `agentcore.turn` logger (`memory.py`). Overlapping invokes in one process mix lines. The tracer binding is a `ContextVar`. The log sink is not.

### Gates that look harder than they are

The copy detector needs six consecutive non-import lines of at least 12 characters (`scripts/check_boundaries.py`). A reformatted paste passes. `CODEOWNERS` lists `@agentcore/platform` on every path, and the file says that team does not exist yet. The lease is a convention. Two agents can edit one package and GitHub will not stop them.

Ruff selects `E,F,I,UP,B,SIM,RUF` and then ignores `S101` in tests. Bandit is not selected, so that ignore does nothing. Mypy is `strict` on package and template `src`, and it does not type-check tests. That is a reasonable bar. Keep it on new templates. Draft #6 turns it off for LangChain (below).

### Style

The implementation is plain and readable. The parts that are heavier than the problem are the per-call thread pool, the hand-rolled JSON Schema subset (justified if Gateway really only accepts that subset, and it should stay a subset), and the amount of eval-pack machinery that simulates products the leases still forbid. Prefer a dataclass or a frozen type for `SessionHandle`, `InvokeResult`, `ToolResult`, and `Verdict` when the next edit touches them. The manual `__init__` plus attribute assignment is consistent, and it is where a typo becomes a public field.

## Draft PRs

### #6 and #7 — do not merge onto current `main`

`git merge-base` of #6 and `main` is `ace165c`, the scaffold. Commits on `main` that this branch does not contain include the judge (PR #1), `agentcore-tools` (PR #2), the eval pack (PR #3), hill-climbing (PR #4), and the thin skills (PR #5). The Origin base is `main`. The branch content is not.

`pyproject.toml` on #6 lists workspace members `agentcore-tracing`, `agentcore-eval`, `minimal-agent`, and `langchain-create-agent`. It omits `primitives/tools`. #7 adds `deepagents-agentcore` and still omits tools. A merge will conflict in `pyproject.toml`, `uv.lock`, `README.md`, `AGENTS.md`, and `CODEOWNERS`. Resolving toward the branch drops the tools package from the workspace.

The invoice desk does not import `agentcore-tools`. It grows `tools.py`, `ledger.py`, and a process-global `_agent` / `set_agent_factory` inside the entrypoint (`templates/langchain-create-agent/src/langchain_create_agent/entrypoint.py`). Offline graders use a scripted model. `hosted_agent` builds `ChatBedrockConverse`, and the tests do not call it. Mypy sets `ignore_missing_imports` for `langchain.*`, `langchain_aws.*`, `langgraph.*`, and `langgraph_checkpoint_aws`. The framework the template exists to pin is outside the type check.

#7 copies the same shape again: entrypoint (~296 lines), ledger, harness, context, scripted model. `scripts/check_boundaries.py` compares templates to `primitives/`, so two templates may clone each other. DESIGN §8 says a template imports primitives. These PRs invent a second tool stack beside the package that landed on `main`, and they edit the platform manifest in the same PR as the template.

The PR bodies are honest that Runtime is skipped. The titles and READMEs still read as the hosted reference. Rebase onto `88bd49d` or later, one template per PR, import `agentcore-tools` for the side-effecting write, and keep the LangChain graph as the model loop only. Until that rebase, these drafts are not the kitchen.

### #8 — acceptable docs PR, keep the skills thin

Fork point is current `main`. Attribution is in `docs/attribution/bojieli-ai-agent-book.md`. The PR says it does not copy the book's skill files and does not claim a Runtime verdict. That matches the diff: docs and four `SKILL.md` checklists, no package behavior.

The same PR amends the rule it is about to exceed. `AGENTS.md` previously limited repo skills to harness, judge, lease, and gate. The diff adds eval-dataset, tool-register, loop-verifier, and experience-to-gate to that allowlist. `agentcore-tool-register` restates `primitives/tools/README.md` and DESIGN §1.6. Useful as a checklist. It is the soft layer DESIGN §1.3 already ranks under the failing gate. Land it only if the overlap map stays the check against a second pstack. Do not let the next agent add another skill that paraphrases a package README.

### #9 — best of the drafts, and it jumps the memory lease

Fork point is current `main`. Separate `infra/uv.lock`, placeholder account ids `000000000000` / `111111111111` / `222222222222` that `is_deployable_account` refuses, per-account names, no cross-stack exports, image URI rejected when it is not in that account's ECR, empty Cedar engine in `ENFORCE`, OIDC via `vars.AWS_DEPLOY_ROLE_*` with `id-token: write` only on the deploy job, and push to `main` can only target dev. Preflight runs before the GitHub environment. Staging and prod deny `bedrock-agentcore:GetWorkloadAccessTokenForUserId`. The PR body matches the code on those points. Synth-without-credentials is the right proof for this PR, and it is not a Runtime PASS.

Must-fix before this becomes the reference deploy:

- **Memory is created and granted.** `AgentCoreStarterStack._memory` builds short-term Memory and `grant_read` / `grant_write` on the runtime role (`infra/agentcore_infra/stack.py`). `agentcore-guardrails` is still a stub. DESIGN §1.5 and §8.7 say guard before write, and memory waits on that guard. A starter stack that grants memory write teaches the opposite.
- **Second `put_record`.** `infra/agentcore_infra/records_fn/put_record.py` reimplements the demo tool against DynamoDB. The package handler is `make_lambda_handler`. The CDK app also calls `gateway.add_lambda_target` while `AgentCoreGatewayClient.sync` creates a target too. Two writers, one tool name (`records` / `put_record`).
- **The smoke step calls the broken judge.** `deploy-account.yml` runs `minimal_agent.judge --harness runtime` after loading stack outputs. That is critical issue 1. `pending-cli-deploy` skips the smoke with exit 0, so a deploy that never created a Runtime stays green. The comment in the workflow is accurate. The green check is still the wrong signal.
- **Resolved decision 3 is rewritten inside the stack PR.** `main` says evals stay in the dev account (DESIGN §7). #9 changes that to three accounts and edits `DESIGN.md`, `AGENTS.md`, and `docs/eval-pass-path.md` in the same diff as the CDK app. The new text is coherent on the branch. A resolved decision should land as its own docs PR before the stack that depends on it, so a revert of the stack does not revert the decision.
- **Deployer IAM is outside the repo.** The runtime role is reviewable. The role in `AWS_DEPLOY_ROLE_*` is "still manual" (`infra/README.md`). `cdk deploy --require-approval never` assumes that role is already least privilege. It is not in this diff, so it is not reviewed.
- **Runtime role is wider than the narrative.** Trust is `aws:SourceAccount` plus `ArnLike` on `bedrock-agentcore` resource `*` in the account. `logs:DescribeLogGroups` is `*`. `logs:CreateLogGroup` and `logs:PutResourcePolicy` are on the runtime log wildcard. X-Ray and `ecr:GetAuthorizationToken` are `*`. Some of that is how those APIs work. The trust `ArnLike` can be the runtime id once the runtime exists. Dev sets Gateway exception level `DEBUG` and allows the user-id workload token. Staging and prod do not. Keep that split.
- **Log destination versus span collector.** The runtime writes `APPLICATION_LOGS` and `USAGE_LOGS` into `/aws/vendedlogs/bedrock-agentcore/std-<env>`. The judge's collector is `CloudWatchAgentSpanCollector` on `AGENTCORE_SPAN_LOG_GROUP`. `docs/eval-pass-path.md` also mentions `aws/spans`. The stack output reuses the application log group as that name. Confirm the collector's query actually reads that group before anyone treats a smoke run as span evidence.

Placeholder ids in git are labeled and blocked at preflight. That is the right kind of placeholder. Do not replace them with real account ids in a later commit.

## Nits

- Golden `capture_traces` runs inside the eval assertion and again in `run_eval`. The lifecycle list in `verdict.json` shows both. Fine for the in-memory exporter. A one-shot collector would make the evidence file empty after the assertion already passed.
- `runtime-evals.yml` injects `AWS_SECRET_ACCESS_KEY` and does not include it in the emptiness check. A key id without a secret still enters pytest.
- `hash_session_id` keeps 32 hex chars of SHA-256. Say "truncated" in any security claim. The function docstring already says "prefix".
- Default tool actor `actor-default` and session `session-local` (`registry.py`) hide a caller that forgot the real ids. Require them the way `require_log_field` already does when they are passed.
- Hill-climbing (`primitives/eval/src/agentcore_eval/hillclimb.py`, `docs/evals/hill-climbing.md`) prints a rhythm and diffs evidence directories. The docs say no production climb has been recorded. Leave it that way until critical issue 1 is fixed.
- Branch names disagree. `AGENTS.md` wants `agent/<id>/<path>/<slug>`. This review branch, #8, and #9 use `cursor/...`. #6 uses `agent/cursor/...`. Pick one in the coordinator prompt.

## What a reference starter fixes first

1. Make `AgentCoreRuntimeHarness` satisfy `minimal-agent.golden-turn`: forward actor (and, when a template needs it, tenant) on the invoke, collect structured logs into `TraceBundle.logs`, and define `tear_down` as the service call or stop claiming it ends the microVM.
2. Make the Runtime workflow fail the check when settings are missing or the status is `SKIPPED`. Keep the JSON word `SKIPPED`. Stop exiting 0 from the job that people will read as the gate.
3. One `runtimeSessionId` representation in logs. Hash on the span. Either hash in the log or name the raw field differently, and stop logging the raw id beside `actorId` until a redaction policy exists.
4. Hold Memory writes until `agentcore-guardrails` has a real `allow_memory_write`. Delete or stop granting Memory in #9 until then.
5. One `put_record`: the package handler, deployed by the stack. Rebase #6/#7 onto that, or close them.
6. Lock the golden cost check to model-reported usage when a model exists. Keep the zero-USD heuristic only on the deterministic `pong:` path, and label that eval so it cannot be cited as DESIGN §1.4.

## Would I let agents copy this structure?

**Yes, with conditions.**

Copy:

- `primitives/` versus `templates/` versus `experiments/`, one lease per prefix, explicit workspace dependencies, `package = false` apps.
- `BedrockAgentCoreApp` versus `RuntimeHarness`, verdict words `PASS` / `PASS+NOTES` / `FAIL` / `SKIPPED`, evidence files that refuse ARNs, stub READMEs that say stub.
- Tool result shape: deny by default, schema errors without values, retryable versus fatal, put-if-absent for the side effect.
- `scripts/check_boundaries.py` as a hard gate, then tighten the shingle once someone pastes around it.

Do not copy, until the list above is fixed:

- `AgentCoreRuntimeHarness` plus `golden_turn.py` as a working Runtime gate.
- `PatternGuard`, `BusinessStub`, the lexical scorer, or `InMemoryHitlGate` as the implementation of those products.
- The #6/#7 workspace manifest, the duplicated ledgers, or the mypy ignores for LangChain.
- #9's Memory grant and the second Lambda `put_record`.
- A GitHub job that exits 0 when the Runtime secrets are empty.

The kitchen is a clear standards sketch with unusually honest docs. It becomes a reference when one independent process can re-run `minimal-agent.golden-turn` on `InvokeAgentRuntime` and get `PASS` for the reasons the assertion names.

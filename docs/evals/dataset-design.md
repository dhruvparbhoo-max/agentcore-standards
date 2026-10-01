# Eval dataset design

A case the harness can run twice is four parts. Drop one and the next run is a different task.

Concepts distilled from `eval-dataset-design` in [bojieli/ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/main/skills/eval-dataset-design). Credit and the skip list: [attribution](../attribution/bojieli-ai-agent-book.md). This page binds those rules to `RuntimeHarness` and the golden dataset in [the eval pack](README.md). It is not a Runtime verdict.

## The four parts

| Part | What it fixes | Where it lives now |
| --- | --- | --- |
| Ticket | Only what the caller would actually say or send. Clarifying a vague request is part of the task. | `turns[].input` — a string prompt, or `{prompt, tool, args}` |
| Caller behavior | What the caller knows, what they will reveal later, and which answers must come from tool results | Approval payloads in the HITL scenarios. A chatty user simulator is not in the pack yet. |
| Initial state | Both sides reset to the same start: books, allowlist, clock, approval deadline | `BusinessStub` copies books per session. `InMemoryHitlGate` takes an explicit `now`. |
| Success criteria | Checks a machine can re-run without trusting the model's write-up | `expected_response`, `expected_trajectory`, `assertions`, `metadata.outcomes` |

`schema_version` is `agentcore-standards.golden.v1`. Unknown JSON keys are load errors. Field roles are listed in [evals/README.md](README.md).

When a later case adds a simulated caller, split what the caller knows (`known_info`) from how they reveal it (`task_instructions`). Any answer about environment state has to cite a tool result. A simulator that invents "yes, that's fixed" lets the agent and the simulator agree with each other.

## What the verifier checks

Prefer a check on state the agent cannot rewrite.

- **End state.** Balance, row count, `replayed`, `status`, allow or block. "The network is back" is not a check. "Speed rating is excellent; poor, fair, and good fail" is.
- **Required actions.** `expected_trajectory` names the tools in order. A tool outside the allowlist leaves the trajectory empty and writes nothing (`crm.write-note-denied`).
- **What the user was told.** `expected_response` is the user-visible string. `result_excludes` fails the case when a forbidden phrase appears. Checking the database and skipping the reply hides a silent success.
- **What must stay true.** The change that should pass, and the behavior that must still pass. `invoice.record-payment-idempotent` records 100.00 USD once; the second call is `replayed` and the balance stays 1150.00. A fix that deletes the assertion, or a second row that happens to look right, fails this pair.

Aggregate with the outcome fields. A single end-state bit can hide a policy break (two tools in one step, a secret in the reply). Add the process check in `metadata.outcomes` or `result_excludes` when the policy matters.

`Builtin.*` evaluators in the optional adapter score spans. They do not replace these asserts. `run_suite` still decides PASS / PASS+NOTES / FAIL.

## Anti-cheat

Do the task once by hand before you freeze the case. Then answer two questions: which reading of the ticket would a careful person accept, and which of those does the verifier accept? What is the cheapest path that gets a pass without doing the work, and does the verifier stop it?

- Vague tickets let the model guess a happy path. Put the ambiguity in the ticket on purpose, or remove it. Do not leave it accidental.
- Parameterize identifiers when a hosted model might have memorized a public instance. The starter pack uses fixed fictional ids (`INV-1042`, `acct-100`, Northwind Traders) so the offline stub stays deterministic. A public case that should not be memorizable generates the ids per run and asserts on the relation, not on one frozen string.
- A canary token in a public task statement makes leakage detectable: if a model emits the token, the task has been seen in training. The canary does not prevent leakage. Keep canaries out of secrets and out of resource ARNs. `write_evidence` already refuses a resource identifier.
- Flaky clocks and shared books make a pass unreproducible. Pass `now` in. Copy state per session.
- Trap cases: the caller says an approval already happened, and policy says it did not. `approve.blocked-without-approval` and `approve.expires` are that shape. The payment stays unpaid.

Label difficulty so a failure points somewhere. A one-tool lookup failure points at tool use. A two-step `invoice.then-crm` failure points at planning across a session. A long trajectory with an approval deadline points at holding the constraint. The starter nine are the current labels; add a slug in `metadata` when you add a rung, and keep the schema keys the loader knows.

## Where cases come from

| Source | Use it for |
| --- | --- |
| Public benchmarks (τ²-bench, SWE-bench, GAIA, and the rest named upstream) | Steal the *shape*: deep checks, parameterization, canaries, a maintained set. Their task mix is not our product mix. |
| Hand-written business cases | Model and harness decisions for this repo. The nine scenarios in `datasets/business.json` are this shelf. |
| Production misses | The highest-value regressions, after someone attributes the first bad step. |

The hill-climbing page already says how a case is sourced and tagged (`capability` or `regression`, `optimization` or `holdout`). Follow [hill-climbing.md](hill-climbing.md) when the case is for a harness climb. A ship gate such as `minimal-agent.golden-turn` can stay untagged.

## Production miss to regression

1. Reproduce the miss once. Keep the trace.
2. Add the case so it fails on that trace. Behavior changes follow [agentcore-encode-miss](../../skills/agentcore-encode-miss/SKILL.md): red gate, then the fix.
3. Tag a climb case `regression` once the fix is in and the case must keep passing.
4. Leave the case in the suite. Today's production failure is tomorrow's floor.

Authoring steps for a single new case: [agentcore-eval-dataset](../../skills/agentcore-eval-dataset/SKILL.md).

## Maintenance

A set rots when the environment moves and the text does not. Budget time to fix four kinds of drift: the fixture world (locked versions, offline data), ambiguous wording, a verifier that is tighter or looser than a human baseline, and an initial state that is not actually reset.

Publishing fewer cases with a higher signal is the point of the review, not a failure to be thorough. Complex Runtime cases spend real tokens. A case that always passes and teaches nothing is a candidate to prune under the hill-climbing rules.

## What this page does not do

It does not claim `InvokeAgentRuntime` was run. Offline `run_suite` on `InMemoryRuntimeHarness` shows the dataset and the stub agree. The independent judge path is [eval-pass-path.md](../eval-pass-path.md).

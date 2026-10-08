# Loop and verifiers

Until a verifier the model cannot edit says the observable holds, "done" is a sentence in the transcript.

Concepts distilled from `loop-engineering` in [bojieli/ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/main/skills/loop-engineering). Credit: [attribution](../attribution/bojieli-ai-agent-book.md). The ship gate for a PR is still a different process: [eval-pass-path.md](../eval-pass-path.md) and [agentcore-judge](../../skills/agentcore-judge/SKILL.md). This page is the loop inside a task. Author steps: [agentcore-loop-verifier](../../skills/agentcore-loop-verifier/SKILL.md).

## Three ways a loop stops too early

| Shape | What the transcript says | What the evidence shows |
| --- | --- | --- |
| Partial work, full claim | "Both items are done." | One tool ran. The second outcome is missing. |
| Give up after one block | "This cannot be done." | Another allowed tool or channel was never tried, and the case required it. |
| False success | "The payment went through." | Status is `pending`. `approve.blocked-without-approval` is this shape: the balance stays 1250.00. |

All three share a cause: the model declared the terminal state. The harness declares it from state.

## Minimal loop

1. The proposer writes a candidate (a tool call, a patch, a reply).
2. Something outside the proposer collects evidence: `RuntimeHarness` output, spans from `capture_traces`, a tool side effect, a policy decision, a rendered artifact.
3. The reviewer reads that evidence and returns a pass or a located defect (which check, how severe, what would fix it). "Looks wrong" is not a defect.
4. On a defect, and while budget remains, the proposer repairs and step 2 runs again on the new candidate. The reviewer looks at the new evidence, not the previous round's story.
5. Budget spent without a pass is a fail or an escalation. It is not a quiet pass.

Three invariants:

- The reviewer reads evidence the proposer did not author as the verdict. A second reading of the same essay adds no new information. Tests, balances, spans, and policy decisions do.
- The reviewer cannot edit the assertion, the evidence writer, or the publish bar. A verifier that can relax itself is a self-approval.
- Only a pass writes durable progress and spends the "this task is complete" quota.

The same split covers safety review and content review: the proposer drafts, the reviewer checks policy on the structured action. HITL is the human form. The approval token has an expiry. `now >= expires_at` stays unpaid (`approve.expires`).

## Premature-completion case

Every template that can say "complete" needs a case where the reply says complete and the world does not. Assert the world: status, balance, row count, trajectory. Assert `result_excludes` if a forbidden success phrase must not appear. The golden pack's HITL scenarios are the current examples.

A harness climb that targets this behavior follows [hill-climbing.md](../evals/hill-climbing.md). The climb diff is not an independent Runtime verdict.

## Budgets

Set a turn cap, a token or cost cap, and a wall-clock cap on the loop. Cost attributes already exist on spans (`cost.tokens`, `cost.usd_estimate`). A loop without a cap and a loop with no verifier fail in opposite directions: one never stops, the other stops while claiming success.

Parallel workers settle on the first **verified** success. Claim the winner with an idempotent lock, then cancel the rest. Two near-simultaneous successes must not both commit. Cost rolls up across agents. The template is still a stub. The new-evidence test for adding an agent is in [the library design](../design/library.md).

## What the author attaches

Eval name, evidence path, which harness ran (`InMemoryRuntimeHarness` or `AgentCoreRuntimeHarness`), status, and what the run did not prove. A missing AWS setting writes `SKIPPED`, not `PASS`.

# Experience loop

A repeated production miss becomes a failing eval. A doc or a skill comes after that gate, and only for judgment the gate cannot check. This repository does not update model weights.

Concepts distilled from `agent-evolution` in [bojieli/ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/main/skills/agent-evolution). Credit and the training skip list: [attribution](../attribution/bojieli-ai-agent-book.md). The gate order is [agentcore-encode-miss](../../skills/agentcore-encode-miss/SKILL.md). The ops checklist is [agentcore-experience-to-gate](../../skills/agentcore-experience-to-gate/SKILL.md).

Saving a trace is not learning. Learning starts when someone judges the trace, writes a check, and shows the check fails on the miss and passes after the fix.

## Two loops

**Online.** The agent finishes the task and appends immutable evidence: spans, structured logs, the eval JSON. It does not rewrite the live prompt, the verifier, or the release.

**Offline.** Group traces, name the first bad step, and propose a change in a PR. A one-off success, or a hostile input, does not edit the agent that is serving traffic.

The two loops meet in the eval suite and, later, in versioned docs and skills. The [library design](../design/library.md) uses the same order: reproduce, add the failing eval or CI gate, then fix.

## Where the lesson goes

| The lesson is | Put it in |
| --- | --- |
| A check a program can run (status, balance, span, banned import, secret marker) | The eval or `scripts/check_boundaries.py` |
| A judgment a person can state, and the gate cannot hold alone | A short doc or a thin skill, after the gate exists |
| A fact about one user | Agent memory, after the guard. Job state stays in the job row. See [the library design](../design/library.md). |
| A weight update, a DPO pair, a reward function, a LoRA | Out of scope. `post-training-strategy`, `reward-design`, and `bad-case-to-dpo` are on the skip list. |

Prefer the row that a machine can fail in CI. A skill as the only control leaves the miss open.

## Verifiers, outcome first

Judge a trajectory in three layers. Build them in this order:

1. **Outcome.** Read the environment: the balance, the row count, the tool side effect, the span tree. This is more reliable than the model's report.
2. **Process.** Policy, allowlist, approval token, "the action the model claimed is the action that ran." A green test after the agent deleted the assertion fails this layer.
3. **Quality.** An LLM rubric, used after 1 and 2 exist, and pointed at the trace. Groundedness in the eval pack is a lexical stand-in for this layer. It does not outrank the outcome assert.

A learning record needs four fields: success, partial, or fail; the result of each layer you ran; where in the trace the evidence sits (turn, tool call, span); and a failure label. A single score cannot tell the next PR what to edit. If the evidence is thin, leave the case out of the regression set. Freezing a low-confidence guess as a test teaches the suite the wrong lesson.

The proposer of a prompt or skill edit and the verifier of that edit are different. The patch is a small diff with a source trace. It has to improve the case that failed and hold the cases that already passed (the hill-climbing regression gate when the change is a harness climb). The author does not edit the assertion to make the miss disappear.

## Safety bounds

- Tool output, and any model summary of tool output, is evidence. It is not an instruction to change the harness.
- Candidate behavior lands in a PR on a branch. The running process does not overwrite itself.
- The agent does not modify the verifier, the boundary script, the evidence writer, or the retained judge artifact. A threshold the agent can lower will hide a regression.

Self-modifying harnesses, browser trajectories compiled into unattended workflows, and sleep-time retraining are deferred. See the attribution page. The offline loop above is the paved path: fail, eval, doc or skill.

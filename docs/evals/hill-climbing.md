# Hill-climbing a harness

This is the operating rhythm for improving an AgentCore harness once Runtime, tracing, and AWS are already hooked up. It encodes how a change is sourced, measured, and accepted.

It does not record a production climb. Nothing in this page is a Runtime `PASS`.

The rhythm is adapted from LangChain's [Better Harness: A Recipe for Harness Hill-Climbing with Evals](https://www.langchain.com/blog/better-harness-a-recipe-for-harness-hill-climbing-with-evals) (Vivek Trivedy, April 8, 2026). That recipe is data sourcing, experiment design, optimization, then review and acceptance. Their traces go to LangSmith. Ours go through `RuntimeHarness.capture_traces` and, on the service, the span log group. This repo does not call LangSmith.

## Plain language

You do not get a better harness by editing until a demo looks right. You get one by keeping a small set of cases that say what the agent should do, changing one thing, and checking that the cases you did not stare at still hold.

### 1. Source and tag

A case comes from one of three places:

- Someone writes it by hand, because they know the behavior production needs.
- A real turn goes wrong. The trace, a dogfood report, or a user correction becomes the next case.
- An external task is useful only after a person edits it so it measures the behavior this agent is supposed to have.

Each case gets three tags:

| Tag | Values | What it means |
| --- | --- | --- |
| Behavior | capability or regression | A capability is a behavior you are still climbing toward. A regression is a behavior that already works and must keep working. |
| Split | optimization or holdout | The optimization set is what you may read while you edit. The holdout set is what you run after the edit is frozen. |
| Topic | a short slug such as `tool_selection` | The kind of behavior. Topics are how you keep the two splits about the same things. |

A case that always passes and no longer teaches anything gets pruned later. The set is not supposed to grow forever.

Ship gates such as `minimal-agent.golden-turn` can stay untagged. They are the merge check. They are not the hill you climb.

### 2. Optimization versus holdout

Split each topic. Some of its cases go in the optimization set. Some go in the holdout set. The holdout should look like the same kinds of work, not like a junk drawer of leftovers.

The optimization set is the one you open. You read those traces, see the miss, and edit the harness against them.

The holdout set stays closed while you edit. You run it after the change is frozen. If you peek and then edit again, that case is no longer holdout: move it to optimization and choose a new holdout case for that topic.

This is the same idea as a train set and a test set. The loop will happily overfit whatever it can see. The holdout is how you notice.

When a topic has a lot of cases, climb a small sample that still covers the topic, then scale up. Do not tune on every expensive case first.

### 3. Baseline

Before the edit, run the current agent version on both splits. Save the evidence. Every later claim is "compared with this run," not "it felt better."

### 4. One harness change

Change one concern. That is usually an instruction, a tool description, or the instruction and the tool that only work as a pair. A second, unrelated behavior waits for its own pass through this loop.

Typical changes:

- The agent keeps misreading a tool result, so you add one instruction.
- The agent calls the wrong tool, so you fix that tool's description and, if needed, the line that says when to prefer it.
- The agent loops on near-duplicate searches, so you bound that step.

Run the same two splits again. Save that evidence next to the baseline, under a different directory.

### 5. Validate regressions

Look at two questions, in this order:

1. Did any case that used to pass now fail? That includes capability cases you already had working, regression cases, and the holdout. A higher overall score that breaks a passing case is not a promotion.
2. Did the capability cases you meant to fix actually start passing, including on the holdout for that topic?

A net gain with a few new failures is common. Those failures go back into the next edit. You do not drop them to keep the gain.

### 6. Human review

A person reads the diff, the traces, and the edge cases a score skips. The usual rejects:

- The new instruction only makes sense for the optimization examples.
- The assert passes because the agent found a shorter path that is not the behavior you wanted.
- The change spends a lot of tokens to satisfy one case and does not show up on the holdout.

Scores are the signal. They are not the acceptance.

### 7. Promote or prune

Promote means the human accepts the change and a separate judge re-runs the Runtime path. The author of the change does not get to call that `PASS`.

Prune means you remove a case that is saturated (the current models always pass it) or that no longer matches the behavior you want. Prune in its own change, take a fresh baseline, and do not delete a failing case to make the score look clean.

### Flywheel

Every production turn leaves a trace. A trace where the agent was wrong is a candidate case. A trace where a person corrected the agent is a better one. You redact it, write the outcome you wanted, tag it, and put it on a side of the split.

More real use produces more traces. More traces produce more cases. More cases make the next harness change face the failures users actually hit. That is the loop. It only turns if the traces exist and someone keeps the dataset honest.

## What this page is not

- Not a result. No production traces were mined here, and no harness was climbed.
- Not a ship verdict. `PASS` / `PASS+NOTES` / `FAIL` still come from a different process that re-runs Runtime (DESIGN §1.1, §4.2, §8).
- Not a waiver for holdout. Editing against the holdout and then reporting the holdout score is not a climb.
- Not permission to store secrets, account ids, or resource identifiers in a case or an evidence file.

## Technical

### Tags

Climb cases carry `DatasetTags` from `agentcore_eval.tags`. Untagged evals stay valid and are ignored by the climb filter.

```python
from agentcore_eval import Eval
from agentcore_eval.tags import BehaviorTag, DatasetTags, SplitTag

EVAL = Eval(
    name="tool.choose",
    rubric="Selects the invoice tool when the user asks for an open balance.",
    act=act,
    assert_=assert_,
    tags=DatasetTags(
        behavior=BehaviorTag.CAPABILITY,
        split=SplitTag.OPTIMIZATION,
        categories=("tool_selection",),
    ),
)
```

| Field | Rule |
| --- | --- |
| `behavior` | `capability` or `regression` |
| `split` | `optimization` or `holdout` |
| `categories` | One or more slugs matching `[a-z][a-z0-9_]{0,63}`. Stored sorted and unique. |

A climb case sets all three. `audit_dataset` fails when any topic has optimization cases and no holdout, or holdout cases and no optimization. A suite with zero tagged evals audits clean: that is a ship-gate suite, not a climb dataset.

Once a capability case still passes on a later baseline, retag it `regression` in a dataset change. Do not retag it inside the candidate you are comparing.

### Evidence

`run_eval` writes the tags into the evidence JSON only when the eval has them. Untagged bundles keep the previous keys (`agent_version`, `eval`, `failures`, `logs`, `notes`, `spans`, `status`). Tagged bundles add `behavior`, `split`, and `categories`.

`write_evidence` still refuses a resource ARN. `evidence/` is gitignored. Do not commit a mined trace.

### Commands

The loop command is the existing harness plus one module. It does not add a second runner and it does not call `InvokeAgentRuntime` by itself.

```bash
uv run python -m agentcore_eval.hillclimb steps
uv run python -m agentcore_eval.hillclimb audit --suite <suite>
uv run python -m agentcore_eval.hillclimb filter --suite <suite> --split optimization
uv run python -m agentcore_eval.hillclimb filter --suite <suite> --split holdout
uv run python -m agentcore_eval.hillclimb filter --suite <suite> --behavior regression
uv run python -m agentcore_eval.hillclimb compare \
  --baseline evidence/baseline \
  --candidate evidence/candidate
```

Baseline and candidate runs use `run_tagged`, which filters and then calls `run_eval` on whatever `RuntimeHarness` you already pass to `run_suite`:

```python
from pathlib import Path

from agentcore_eval.hillclimb import run_tagged
from agentcore_eval.tags import SplitTag

report = run_tagged(
    Path("<suite>"),
    harness_factory=harness_factory,
    agent_version="<version>",
    evidence_dir=Path("evidence/baseline"),
    split=SplitTag.OPTIMIZATION,
)
```

Run it again with `SplitTag.HOLDOUT` before the edit, then again for both splits after the one change, with `evidence_dir` pointed at `evidence/candidate`. Names are unique, so both splits can share a directory. Subdirectories are fine too: `compare` walks `*.json` underneath the path you give it.

On the service, `harness_factory` is `AgentCoreRuntimeHarness.from_env` after `AWS_ACCESS_KEY_ID`, `AWS_REGION`, `AGENTCORE_RUNTIME_ARN`, and `AGENTCORE_SPAN_LOG_GROUP` are set in the environment. Those values stay out of git. The in-memory harness is how you debug the case. It is not the baseline you promote from.

`filter` prints `name`, `behavior`, `split`, and categories. It exits 1 when nothing matches. `audit` exits 1 when a topic is missing a side. `compare` exits 1 when the diff is blocked or the directories cannot be read. `steps` exits 0 and only prints this rhythm.

### What compare blocks

`compare_evidence` reads the evidence JSON. It does not re-invoke the agent.

| Baseline → candidate | Result |
| --- | --- |
| `PASS` or `PASS+NOTES` → `FAIL` | Regression. Blocks. Applies to capability, regression, optimization, and holdout. |
| `FAIL` → `PASS` or `PASS+NOTES` | Gain. Does not block. |
| `PASS` → `PASS+NOTES` | Note for the human. Does not block. |
| `PASS+NOTES` → `PASS` | Recorded as a gain. Does not block. |
| Same status | Unchanged. A still-failing case stays visible and does not block. |
| Case missing from the candidate | Blocks. Deleting a case is a prune, which is a separate change with a new baseline. |
| Case only in the candidate | Reported as unbaselined. It is not a score. |
| `behavior`, `split`, or `categories` differ | Tag drift. Blocks. Retag on a new baseline. |

A clear diff with zero gains is not a climb. Human review decides whether a behavior-neutral change is worth keeping. The printed summary says that, and it says the diff is not a Runtime ship verdict.

`compare` cannot see whether someone opened the holdout traces before editing. That rule stays with the person running the loop.

### Traces and the flywheel

`capture_traces` returns the spans and structured logs for the session. The service path collects those spans from the log group named by `AGENTCORE_SPAN_LOG_GROUP`. A mined case keeps the redacted input, the observable outcome, and the tags. It does not keep the raw evidence bundle.

New failures start as `capability` plus `optimization` or `holdout`, with a topic, and `audit` must still see both splits for that topic. After the behavior holds, a later dataset change retags the case `regression`.

The judge path is unchanged. After human review, a different process re-runs the Runtime evals and records `PASS`, `PASS+NOTES`, or `FAIL`. On this repo that command is `uv run pytest -m runtime`. `hillclimb compare` is not that process. CI green is not that process.

### Acceptance checklist

Use this before anyone calls the change promoted:

1. `audit` is clean for the tagged suite.
2. Baseline evidence exists for both splits, from the agent version you started from.
3. The candidate is one harness concern, not a stack of unrelated edits.
4. `compare` is clear, and any holdout gain is in the same topics you climbed.
5. A person has read the traces and rejected overfitting the optimization set.
6. An independent judge has a Runtime verdict for the ship-gate suite. The climb diff does not substitute for it.

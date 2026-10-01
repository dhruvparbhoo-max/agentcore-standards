# pstack and AgentCore skills

pstack (poteto-mode, its playbooks, and the principle skills) is the general method. Skills in this repo exist only for the AgentCore gap: `RuntimeHarness`, the independent Runtime judge, path leases, the failing-gate order, and `docs/capability-maps/`.

Read this before adding a skill. If a row already says to use pstack, do not write a second copy under `skills/`.

Repo skills live in `skills/<name>/SKILL.md` (DESIGN §8.5). They are not a second tree under `.cursor/skills/`.

## Use pstack. No AgentCore skill.

| pstack | Use it when | AgentCore gap |
| --- | --- | --- |
| **poteto-mode** | Any non-trivial task. It picks the playbook. | None. Start here. |
| **how** | How a subsystem runs, or which package should own a change. | If the answer changes a driveable surface, then `agentcore-capability-map`. |
| **why** | Design rationale and past decisions. | None. |
| **architect** | Types and module shape before code. | None. DESIGN §2 is the catalog. A sketch does not widen a lease. |
| **interrogate** | Adversarial multi-model review of a diff. | Review is not the ship gate. The ship gate is `agentcore-judge`. |
| **arena** | Several implementations of one artifact. Keep a base, graft the rest. | None. |
| **Eval playbook** (`poteto-mode/playbooks/eval.md`) | Blinded bakeoff of agent variants. | A different judge from the Runtime ship check. |
| **figure-it-out** | Large or odd work that matches no narrower playbook. | None. |
| **blast-radius** | What a change can break outside the diff, proved by running code. | None. Scouts use this. The surface list they consult is the capability map. |
| **create-verification-skill** | A project with a UI, CLI, or service and no scripted way to drive it. | Do not run it here. Proof is `RuntimeHarness`. Maps stay in `docs/capability-maps/`. |
| **maintain-verification-skill** | Upkeep of a `verify-*` skill and its feature map. | Do not invent `.cursor/skills/verify-*/`. Update the capability map. |
| **principle-prove-it-works** | Before calling any task done. Check the real artifact. | Then `agentcore-verify` for the harness, evidence file, and ship bar. |
| **principle-separate-before-serializing-shared-state** | Two actors would write one worktree, branch, or file. | Then `agentcore-lease` for the path prefix. |
| **principle-sequence-verifiable-units** | Stacking commits and PRs so each step can be checked. | Lease one path. Land with the Shipping playbook after a Runtime verdict. |
| **principle-encode-lessons-in-structure** | The same correction is about to become another paragraph. | Then `agentcore-encode-miss` for the order: red eval or CI gate, then the fix. |
| **principle-make-operations-idempotent** | Retries must converge. | None as a skill. A side-effecting tool still needs a double-invoke eval (DESIGN §1.6). |
| **swarm** | Parallel coverage or exploration. | Workers still take one lease each. |
| **Orchestrate playbook** | A standing coordinator and many stacked PRs. | Briefs still name one path. Spawn text is DESIGN §8.8. |
| **Shipping playbook** | Landing a stack. Independent PASS / PASS+NOTES, contiguous prefix only. CI green is not a verdict. | `agentcore-judge` produces the Runtime verdict Shipping's control-ui / control-cli paths cannot. |
| **show-me-your-work** | A decision trail for unattended work. | Hillclimb and overnight runs. A ship claim still needs the eval evidence JSON. |
| **tdd** | Someone asked for a failing test, or the bug has a cheap local test. | A local test does not close a Runtime claim. |
| **Hillclimb playbook** (`poteto-mode/playbooks/hillclimb.md`) | One metric, one change, keep or revert, frozen harness, regression gate. | No `agentcore-hill-climb` skill. See below. |

## Hill-climbing

The poteto Hillclimb playbook stays the method. There is no `agentcore-hill-climb` skill.

[docs/evals/hill-climbing.md](../evals/hill-climbing.md) is the command sequence on this repo: `DatasetTags`, `uv run python -m agentcore_eval.hillclimb`, and `compare` of two evidence directories. That compare does not call Runtime and is not a ship verdict. This repo has not recorded a production climb.

When the metric is an AgentCore behavior:

1. Follow the Hillclimb playbook.
2. Freeze one measurement command that calls `run_suite` or `run_eval` on a `RuntimeHarness` and prints the metric. Sensitivity checks may use `InMemoryRuntimeHarness`. A keep on the ship metric names `AgentCoreRuntimeHarness` when the Runtime environment is set, and says the Runtime path was not run when it is not.
3. Regression gate before any keep: `uv run pytest -m "not runtime"` and the template's golden eval.

## Skills that exist here

| Skill | Only what pstack does not already do |
| --- | --- |
| `skills/agentcore-verify/` | `start` / `invoke` / `capture_traces` / `tear_down`, evidence JSON, author draft. Unit tests and CI do not close the ship gate. |
| `skills/agentcore-judge/` | A different process re-runs the claimed eval on `AgentCoreRuntimeHarness`. |
| `skills/agentcore-lease/` | One `packages/<name>/` or one `templates/<name>/` per PR. |
| `skills/agentcore-encode-miss/` | Reproduce, add a failing eval or CI gate, confirm red, then fix. |
| `skills/agentcore-capability-map/` | Edit `docs/capability-maps/` when a driveable surface changes. |

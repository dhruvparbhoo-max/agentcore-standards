---
name: agentcore-judge
description: >
  Independent AgentCore ship check. Use when an author PR is ready and a
  different process must re-run the claimed eval on AgentCoreRuntimeHarness.
  Author and judge are different agents. Interrogate, arena, and the poteto
  Eval playbook do not replace this gate.
---

# Judge a Runtime eval

The poteto **Shipping** playbook owns stack landing: one independent verdict per PR, `PASS` or `PASS+NOTES`, contiguous verified prefix from the root. This skill is how that verdict is produced here. Shipping's `control-ui` and `control-cli` drives do not apply.

## When

You did not write the PR. The author marked it ready and named an eval plus an evidence path.

## Steps

1. Read the PR verdict section and the eval module. Skip the author's chat and any note about why the eval should pass.
2. Check out the PR head in a clean worktree. Leave product code unchanged. A judge does not edit the entrypoint to obtain a pass.
3. Re-run the claimed eval on `AgentCoreRuntimeHarness` (`InvokeAgentRuntime`), in the same AWS account as dev. Isolate with agent version, namespace, and IAM path.

```bash
uv run pytest -m runtime
```

The command needs `AWS_REGION`, `AGENTCORE_RUNTIME_ARN`, and `AGENTCORE_SPAN_LOG_GROUP`. If any is missing, the judge writes `SKIPPED` and exits 1. The `runtime-evals` workflow does the same. Report that as missing evidence, which blocks merge. Do not treat the skip as `PASS`.

4. Read the new evidence JSON. Match it to the observable named in the eval. Keep resource ARNs, account ids, and secrets out of the retained artifact.
5. Emit one status, with the eval name, evidence path, and head SHA:
   - `PASS`
   - `PASS+NOTES` (land is allowed; the notes become a follow-up issue or skill, not a silent waiver)
   - `FAIL` (author reworks on the same lease)

`InMemoryRuntimeHarness`, `ruff`, `mypy`, and a green unit-test job do not count. No further human approval sits on top of `PASS` or `PASS+NOTES` (DESIGN §4.2, §8.4).

## Do not

- **interrogate** challenges the diff from several models. Run it when the design is contested. It does not re-run Runtime.
- The poteto **Eval** playbook blinds a bakeoff of variants. That judge is not this gate.

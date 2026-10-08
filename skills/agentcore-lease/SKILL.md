---
name: agentcore-lease
description: >
  Take one package or one template path for an AgentCore PR. Use before
  editing when a task spans packages, or when another agent might write.
  Run principle-separate-before-serializing-shared-state first.
---

# One path per PR

Run **principle-separate-before-serializing-shared-state** first, so two writers do not share a worktree. This skill is the path prefix in [AGENTS.md](../../AGENTS.md). The shared choices are in [the library design](../../docs/design/library.md).

## When

You are about to implement, or the task names two packages, a package and a template, or `pyproject.toml`.

## Steps

1. Read the lease table in `AGENTS.md`. Confirm that path is yours. Scouts may read any path. A writer without a lease stops.
2. One PR writes one `primitives/<name>/` or one `templates/<name>/`. A miss encoded as docs or a gate may touch `docs/`, `skills/`, and `.github/` (lane G) and must leave product APIs alone.
3. Use a branch named `agent/<id>/<package-or-template>/<slug>` for package or template work.
4. Stay inside the lease. A missing API is a blocker to report. Do not edit the other package. Templates import packages. `scripts/check_boundaries.py` fails the build when a template copies package source or imports `experiments/`.
5. Leave `pyproject.toml` and `uv.lock` alone unless the lease includes the platform manifest. Adding a workspace member is a platform change. Declare a workspace dependency in the member that imports it.
6. Memory waits on guardrails. Do not start lane B, C, or D until a judge PASS exists for the real Runtime golden eval. Do not land a stack tip while a lower PR lacks an independent Runtime verdict.

## Do not

**swarm** and the **Orchestrate** playbook fan out work. They do not grant a second writer on the same prefix. **architect** does not widen the lease.

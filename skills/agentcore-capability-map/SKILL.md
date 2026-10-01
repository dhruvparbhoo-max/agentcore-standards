---
name: agentcore-capability-map
description: >
  Update docs/capability-maps when an AgentCore entrypoint, tool, Memory
  namespace, Gateway target, approval gate, drive path, or success
  observable changes. Use after the how skill. Do not start a second feature
  map under .cursor/skills.
---

# Update the capability map

Run **how** when you still need the runtime picture. This skill writes that picture into `docs/capability-maps/`. DESIGN §6 maps Lauren's feature map to the template README plus these files.

Do not run **create-verification-skill** or **maintain-verification-skill**. Those maintain `.cursor/skills/verify-*/features/`, which this repo does not use.

## When

You changed an entrypoint, tool, Memory namespace, Gateway target, approval gate, drive command, or the observable an eval asserts.

## Steps

1. Edit `docs/capability-maps/<template-or-package>.md`. Create it for a new surface. Keep `docs/capability-maps/README.md` in sync.
2. Record, for the surface you changed:
   - entrypoint (module, handler, how it is served)
   - how to drive it (payload and which `RuntimeHarness`)
   - tools, Gateway targets, Memory namespaces, and approval gates (write "none" when the surface has none)
   - the observable that proves success (eval name and the checks)
3. Match the eval. A map line the eval does not check is unfinished. Fix the map or the eval in the same PR when that lease is yours. A docs-only map correction is lane G.
4. Scouts may write under `docs/capability-maps/` only. They do not open product PRs.

The current shape is `docs/capability-maps/minimal-agent.md`.

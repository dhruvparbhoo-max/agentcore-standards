# agentcore-tools

Stub for lane C. Not implemented.

Owns tool registration, Gateway binding, schema validation, and idempotency wrappers (DESIGN §2.2). Side-effecting tools need a double-invoke eval before they merge.

Do not add a `pyproject.toml` until `packages/agentcore-tools/` is leased. Do not fork this into a template. If a template needs a tool API, file a blocker instead of copying code.

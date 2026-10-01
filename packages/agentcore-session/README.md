# agentcore-session

Stub for lane B. Not implemented.

Owns Runtime session lifecycle: `start`, `invoke`, `end`, sticky routing, idle/TTL, cold-start metrics (DESIGN §2.1). Depends on lane A (`agentcore-tracing`, `agentcore-eval`).

Do not add a `pyproject.toml` until a coordinator leases `packages/agentcore-session/` and the platform lease for the workspace manifest. One writer. No second agent in this directory.

Required later evals: sticky reuse, new session after terminate, cross-tenant isolation, cold versus warm latency.

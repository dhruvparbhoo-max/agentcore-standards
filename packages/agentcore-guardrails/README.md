# agentcore-guardrails

Stub for lane D. Not implemented.

Owns Bedrock Guardrails config as code: `apply_input`, `apply_output`, and `allow_memory_write` (DESIGN §2.4). Guardrail ids and versions will be pinned in config, not hardcoded ARNs in git.

Land this before `agentcore-memory`. Memory writes go through the guard. Do not start a writer here without a lease on `packages/agentcore-guardrails/`.

# agentcore-guardrails

Input, output, and memory-write checks. See [the library design](../../docs/design/library.md). Version 0.1.0.

`Guard()` runs local policy `1.0.0`. Injection and secret-shaped text are blocked. The reason does not include the text. Email, phone, and national-id shapes are replaced. `screen_memory_write` returns the text a memory client may store. `allow_memory_write` is true only for that sanitized result.

`Guard(..., require_service=True)` blocks when the backend is missing or raises. `bedrock_backend` calls `apply_guardrail`. That call is not a Runtime PASS.

Pin ids are names. A policy version other than `1.0.0` raises before a check runs.

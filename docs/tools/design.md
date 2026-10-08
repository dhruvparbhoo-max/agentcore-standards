# Tool design

A tool is a goal the agent can finish in one call, with a schema the registry can reject. Wrapping every API route as its own tool forces the model to orchestrate the endpoint list.

Concepts distilled from `tool-design` in [bojieli/ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/main/skills/tool-design). Credit: [attribution](../attribution/bojieli-ai-agent-book.md). The implementation shelf is `primitives/tools` (DESIGN §2.2). Registration steps: [agentcore-tool-register](../../skills/agentcore-tool-register/SKILL.md).

## Shape

Ask two questions separately. What form is this capability? How many definitions sit in the session at once? The second question is [discovery](discovery.md).

Prefer one tool per goal the agent actually has. `read_document(file_type=...)` beats three extractors that differ only by file type. Split a tool when one of these is true:

| Pressure | Why a dedicated tool |
| --- | --- |
| Security, audit, or an irreversible side effect | Gateway policy and an idempotency key have to bind to a name |
| The parameters are a nested object with joint rules | A JSON schema rejects the bad call before the handler |
| The call is on the hot path | A stable name is easier to trace than a generated command |
| Platform differences would leak into the prompt | The tool hides them and returns one error shape |

An open code interpreter is not the paved path. Templates call tools through Gateway. Deny-by-default is the policy: `Policy` starts empty, a forbid wins over a permit, and Cedar on the real Gateway uses the same posture.

`@registry.tool(name, schema, description, idempotent=True)` registers a tool. A side-effecting tool with `idempotent=False` raises `IdempotencyRequired`. Schema checks are a JSON Schema subset. Rejection messages name the path and the expected type. They omit the rejected value. A breaking schema change bumps `schema_version` and goes through `assert_schema_evolution`.

## Descriptions

Most wrong-tool calls are a description that never said what the tool will not do.

- Say when to call it, not only what it can do.
- State the boundary. A name search that cannot search file contents has to say so.
- Give a concrete parameter example (`2024-03-15T14:30:00Z`, not "a timestamp").
- Say what comes back, and what it costs in time or tokens, including the cheaper call when the agent only needs metadata.
- Put one to five real invocations in the description or in the eval fixture. Schema types do not carry unit conventions.

When the agent keeps picking the wrong tool, edit the description before you change the model.

## Argument fidelity

The model must see the same values the handler runs. Silent rewrites and silent extra arguments produce failures the model cannot diagnose: the read path returns one string, the write path matches another.

If you must normalize, say so in the description, and put the normalized value in the tool result. Fail closed on path traversal, command injection, and type errors. Do not "helpfully" repair them.

## Perception tools

Search returns a structured candidate list (title, location, snippet), a cursor, and the total. Reading supports offset and limit. Truncation is explicit: which range was returned, how much remains, how to continue. A silent cut makes the agent treat a prefix as the whole document.

Read-only results may be cached. Parallel read-only calls are safe. A large payload stays out of the trajectory; the result points at the stored body and returns a marked preview. See [context budget](../runtime/context-budget.md).

## Execution tools

Order the controls:

1. **Validate** inputs. Reject fast.
2. **Authorize** with Gateway. No matching permit is a deny. One policy engine per agent version, so an old permit does not outlive that version.
3. **Review** irreversible work (payment, outbound message, IAM change) with a reviewer that sees different evidence than the proposer's essay, or with the HITL gate. Rejection comes back as a tool result that includes the reason. `templates/human-in-the-loop` is still a stub; the eval-pack gate is `HitlGate` (`approve.*` scenarios).
4. **Sidecar or guard** on the structured tool fields only (`tool` name and arguments). Free text in the same prompt is an injection path. A burst of refusals escalates to a person. It does not retry forever.
5. **Verify** when the result is checkable (lint after a write, balance after a payment) and return that check in the tool result.

Idempotency follows DESIGN §1.6. `put_record` is put-if-absent on `record_id`, and the registry replays the first result for a repeated idempotency key. The same key with different arguments is a fatal conflict and does not run the handler. Email, phone, and outbound transfer do not become idempotent by retrying. Use a precheck, then a confirm. A failed confirm returns the error to the model for a new plan.

`tools.double-invoke` is the local evidence that one key produces one handler run and one stored row. A new side-effecting tool needs the same shape of evidence. Live Gateway invocation is outside that local check. The package README states what a local run proves.

Sandbox talk belongs to untrusted code execution. A virtualenv isolates packages. It does not isolate the filesystem, the network, or processes. Runtime microVMs are scratch (DESIGN §1.5). Durable facts wait for Memory, and Memory writes wait for guardrails.

## Collaboration tools

Spawn, cancel, and message are the multi-agent template's problem, and that template is a stub. Until it exists, a handoff is a structured payload with a goal, constraints, and artifact refs. See [multi-agent](../orchestration/multi-agent.md).

A sub-agent prompt, when you write one, names the role, tags where each block came from (`FROM_MAIN_AGENT`, `FROM_USER`, `TOOL_RESULT`), states what it must refuse, and fixes the output shape. HITL timeouts have a default that fails closed. The approval, the denial, and the reason are evidence, not a chat aside.

## Traces

Every permitted call opens `tool.<name>` and a child `gateway.call`. Logs go through `agentcore.turn` with the hashed session id, actor, agent version, request id, tool name, latency, and error class. Arguments are not logged.

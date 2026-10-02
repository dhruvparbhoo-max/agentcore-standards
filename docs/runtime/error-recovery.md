# Error recovery

Classify the fault before you retry. A rate limit, a bad argument, a broken transcript, and a loop that is not moving are four different repairs.

Concepts distilled from `error-recovery` in [bojieli/ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/main/skills/error-recovery). Credit: [attribution](../attribution/bojieli-ai-agent-book.md). Tool errors already split `retryable` and `fatal` in `agentcore-tools`. This page is the session-level map. It does not claim a Runtime pass.

## Four layers

| Layer | Examples | Repair |
| --- | --- | --- |
| API | 429, overload, connection drop, idle stream, output truncated | Retry with backoff and jitter, or change the request (higher output cap, continue from the break, a fallback model). |
| Tool | Unknown tool, schema rejection, handler exception, the same fingerprint forever | Return a structured tool result. Do not retry a fatal error unchanged. |
| Context | Window overflow, a tool call with no paired result | Compress or isolate ([context budget](context-budget.md)). Repair pairing before the next model call. |
| Control flow | The same call with no new state, or recovery code that calls the model and fails again | Stop that path. Count consecutive failures. Escalate. |

`invoke_tool` already treats timeout and over-budget latency as retryable and sets `backoff_ms`. Fatal results have no backoff and are cached. Schema rejection does not run the handler. Same idempotency key with different arguments is a fatal conflict.

Fingerprint a tool call as name plus canonical arguments. The same fingerprint with the same error is "no progress", not a transient blip.

## Escalate in order

1. **Silent retry** for retryable API faults on the foreground turn. Exponential backoff plus jitter. Honor a server-supplied wait. Background work (title, suggestion, memory extract) fails open and does not retry: those retries steal the foreground quota.
2. **Change the request** when retrying the same bytes cannot help. Raise the output limit once, then ask the model to continue. A fallback model is a product decision and is not wired in this repo. If you add one, store the trajectory in the neutral form below so the next model can read it.
3. **Tell the user** after the automatic steps are exhausted, including which steps ran.

Hold intermediate errors inside the recovery loop. Downstream subscribers and the user see the outcome, plus the list of attempts if recovery fails.

Tool-layer faults stay in the session. The model receives "tool does not exist", or the schema path that failed, as an ordinary tool result, and the next turn can correct the call. More specific errors are easier to correct. Do not paper over a malformed argument by guessing a value (see [tool design](../tools/design.md)).

## Caps

Every recovery path has a ceiling: consecutive failures, turns, and a session budget. Pick the numbers from production counts when you have them. Until those counts exist, still set a ceiling. An uncapped compressor or an uncapped retry is how one stuck session spends the error budget for everyone else.

The death spiral is recovery that calls the model. A context overflow that triggers "summarize, then commit, then extract memory" can overflow again inside the hook. On the error path, skip model side effects. A depth counter stops a residual chain. The outer stop is the turn cap plus the session budget plus an escalation to a person.

Streaming resume is not implemented on `RuntimeHarness`. When it is, record where the stream broke (reasoning, assistant text, or tool arguments). A half tool call is text until it parses again. If a tool already ran because the stream executed early, dedupe with the call fingerprint before the resume so the side effect happens once. DESIGN §1.6 still applies.

A live connection that sends nothing is different from a connection that drops. The idle watchdog is part of the API layer. A connect timeout does not see a stall.

## Neutral trajectory

Spans and structured logs are the record we keep (`agent.turn`, `tool.<name>`, `gateway.call`, hashed session id, error class). Provider thought signatures and vendor-only blocks are not that record. If a later failover rewrites history for another model, drop those credentials and keep tool name, arguments, and result text. Rewriting history as prose is the strict option when the destination rejects foreign signatures. After a switch, watch for a repeated fingerprint so a tool does not run twice.

Eval fixtures that are missing a paired tool result should fail closed. Inserting a placeholder so a broken trace looks valid hides the bug. Product sessions may repair the pairing so the next model call is well-formed; say so in the trace.

## Eval

A recovery change needs a case that distinguishes retryable from fatal, and a case that stops after the cap. The local tools suite already covers retryable versus fatal and the double-invoke replay. A session-level death-spiral test belongs with the template that implements the loop. Author evidence still goes through [agentcore-verify](../../skills/agentcore-verify/SKILL.md). CI green on unit tests is not the ship verdict.

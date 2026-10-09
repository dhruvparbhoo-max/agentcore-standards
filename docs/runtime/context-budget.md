# Context budget

The model sees a static prefix plus a trajectory that only grows. Keep the prefix byte-stable. Put clocks, counters, new tool schemas, and compressed tool results at the end.

Concepts distilled from `context-compression`, `agent-state-bar`, and `kv-cache-design` in [bojieli/ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/main/skills). Credit: [attribution](../attribution/bojieli-ai-agent-book.md). Span cost attributes live in `agentcore-tracing`. This page does not add a cost gate and does not record a measured cache hit rate for this repo.

## Prefix

The prefix is the system prompt and the tool schemas that were present when the session started. A one-character edit, a timestamp, or a per-request example swap invalidates the cache from that token onward. Dynamic facts are new messages at the end.

- Order the prefix for cache stability first, then for readability.
- Each runtime flag you bake into the prefix doubles the cache variants. Put those flags after the boundary.
- Append a newly discovered tool schema at the end and leave it there ([discovery](../tools/discovery.md)).
- Use the provider's message roles. Hand-built `USER:` / `ASSISTANT:` strings leave the format the model was trained on.
- When a tool result is replaced by a preview, freeze that replacement string. A later session that wants the same cache prefix must reuse the same bytes.

Prompt-cache prices and APIs differ by provider. Read the current provider note before you depend on a discount. The architectural rule above does not.

## State bar

Long trajectories hide the goal, the open TODOs, and how many times a tool has already run. The model can look those facts up by scanning, and it often spends the thinking budget doing that scan. A state bar is the same facts, computed by code, in a short block at the end of the messages.

Include only what the loop needs: open TODOs and their status, per-tool counts against any cap, the last error class, and the harness clock you already pass into gates (`now`). Wrap it in a label such as `<agent_status>` so it is obviously harness output, not a user turn.

Rules:

- Compute it from the trace and the tool ledger. Do not copy untrusted tool text into it. The model treats the bar as ground truth, so poisoned tool output in the bar becomes a trusted instruction.
- Append or replace the bar at the end. Do not edit the system prompt to refresh it.
- Replacing the previous bar (one slot, rewritten each turn) keeps a single status. Appending a new bar each turn preserves history and costs more tokens. Pick one and keep it stable for the session.
- The bar is a complement to compression: code writes a conclusion in, compression takes a bulky raw result out.

## Compression

Compress tool results between model calls, not by rewriting the prefix mid-call.

Do it when prompt tokens cross a high-water mark you chose (the source uses "approaching the window", on the order of most of the budget). Compress the unmarked tool results in one batch. Mark them so a later pass skips them. Compressing every turn burns the prefix cache for a small saving.

Preserve four kinds of content explicitly:

| Keep | Why |
| --- | --- |
| Decisions | Later turns need the choice, not the search that led there |
| Constraints | The reason a rule exists disappears first |
| Failures | A dropped failure gets retried as if it were new |
| Citations | The summary can be lossy if the source id remains |

Drop navigation chrome and unused search hits. Summarizing noise still costs a model call. Keep times, names, and amounts intact. A summary that drops them is worse than the raw text.

Query-aware compression (the compressor sees the task and what is already known) is the strategy the source found worth the tokens. The experiment tables and model names stay upstream. Do not treat those figures as numbers this repo measured.

A specialist that returns a short conclusion isolates the bulk better than compressing after it has entered the main trajectory. The specialist's task text has to carry the goal and the constraints, because it does not see the parent's full transcript. Isolation is the multi-agent move in [the library design](../design/library.md), and only when that specialist produces evidence the parent could not see by rereading itself.

If compression itself fails repeatedly, stop and surface the error. That cap is the same rule as [error recovery](error-recovery.md): the recovery path does not call the model in a loop.

## What to assert

A context-budget change that is user-visible needs an eval on the outcome (the reply and the tool side effect still match), plus the span tree and cost attributes the golden turn already checks. A smaller prompt that drops a required citation fails `result` or the groundedness rubric. Offline green is not a Runtime verdict.

# agentcore-agent

Turns a pattern folder into a running agent and keeps its controls checkable.

- `load_pattern(folder)` reads and validates `pattern.yaml`. Every problem is reported at once.
- `build_agent(config, tools=..., model=...)` returns a session with `run`, `stream`, `pause_for_human`, and `resume`. The `framework` field picks the loop:
  - `create_agent` (default): LangChain's tool-calling loop. Risky tools pause through the LangGraph interrupt.
  - `strands`: the Strands agent loop. Risky tools pause through a `BeforeToolCallEvent` hook. Install the `strands` extra.
  - `harness`: the AgentCore managed loop, called with `InvokeHarness`. It cannot pause, so a pattern with risky tools cannot pick it.
- A risky tool (send, spend, delete, change) runs only after its handler spends an approval token bound to the tool name, the argument hash, and the actor. A different person must approve.
- `script=` swaps in a scripted model for offline tests and `make local`. A deploy never uses it.

Model providers stay outside this package. The caller passes the chat model the config names.

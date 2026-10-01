# Context engineering

The system prompt is the stable prefix. Write it as a short procedure with rules a test can apply. Load everything else when the turn needs it.

Concepts distilled from `context-engineering` in [bojieli/ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/main/skills/context-engineering). Credit: [attribution](../attribution/bojieli-ai-agent-book.md). Layout of the prefix, the state bar, and compression: [context budget](../runtime/context-budget.md). This page is the prompt. It is not a cookbook of sample prompts.

## What the API actually sends

Each invoke rebuilds the message list. The model does not remember the previous HTTP call. The harness sends:

- one system message at the front (developer rules)
- user, assistant, and tool messages for the trajectory
- tool definitions beside the messages, not stuffed into a user turn

The model requests a tool call. The framework runs it and appends the result. That loop is the entrypoint's job (`@app.entrypoint` on `BedrockAgentCoreApp`). Evals drive it through `RuntimeHarness.invoke`.

A careful new teammate who cannot act from the system prompt will match the model's confusion. Read the prompt that way before you add adjectives.

## How to write the prefix

- **Procedure, then exceptions.** Name the stages (validate, classify, act, verify) so a turn knows where it is. A flat list of prohibitions makes the model search for a matching line.
- **Rules a test can fail.** "Pick a sensible fee" becomes "refunds use `fixed_fee`; percentage fees are refused." The eval asserts the fee field or `result_excludes`. Product states the rule. The engineer encodes it and does not invent a second business rule in the prompt.
- **Reserve uppercase absolutes** for the few constraints that must always hold (no secrets in the reply, no tool outside the allowlist). A prompt of absolutes is a prompt with no emphasis.
- **Examples are part of the prefix.** Two or three fixed examples that cover the boundaries, for a task type, beat ten near-duplicates. Retrieving a fresh example on every request rewrites the prefix and makes the run unreproducible.
- **Tone is cheap.** It changes the wording more than it changes whether the tool ran. Spend the edits on the procedure and the tool descriptions. Clearing a tool description and leaving the signature raises wrong-tool calls; see [tool design](../tools/design.md).

Skills in this repo are the on-demand layer: YAML `name` and `description` route, the body loads when the task matches, and the body is appended to the trajectory so the prefix stays put. The description states when to use the skill and when not to. A description of "helps with backend" matches everything. Before adding a skill, read [pstack versus AgentCore skills](../skills/pstack-vs-agentcore.md).

## Injection at the context layer

Treat text that entered from outside the developer prefix as data.

- Wrap it and name the source (`<external_content source="webpage">`).
- Keep tool results in the tool role. The state bar is a harness message with its own label, computed by code ([context budget](../runtime/context-budget.md)).
- Phrase filters (the offline `PatternGuard` blocks `ignore previous instructions`) are a backstop. Wording variants walk around them. The pack's guardrail fixtures document the offline stand-in. `agentcore-guardrails` is still a stub.
- The hard layer is Gateway policy, least-privilege credentials, and a reviewer on structured tool fields ([MCP and skills](../tools/mcp-and-skills.md)). Context hygiene lowers the chance of a bad call. It does not replace the deny.

A skill body is instructions loaded from a file. Review it before it is on the index. A state bar built from untrusted tool text is an injection into the most trusted slot in the turn.

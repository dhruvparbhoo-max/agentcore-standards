# agentcore-langchain

`create_agent` over the AgentCore tool registry. See [the library design](../../docs/design/library.md). Version 0.1.0.

`registry_callables` builds one function per registered tool. Each function parses a JSON object and calls `ToolRegistry.invoke_tool`, then `compact_tool_output` on the string returned to the model. Call them inside `bind_turn`. `turn_from_headers` uses `agentcore-identity`.

`create_runtime_agent` passes those callables and the system prompt to `langchain.agents.create_agent`. The caller supplies the model. This package does not choose a provider and does not grant tools. An empty policy still denies the call.

`prompt_from_context` turns an `AssembledContext` into that system prompt.

`build_langchain_agent` is the entrypoint helper: checkpointer, middleware, and `context_schema`. `agent_middleware` puts human approval first. `before_redaction` is where a template inserts `Guard` and context assembly. `compact_tool_result` keeps structured fields in a long tool JSON payload. `AGENTCORE_MEMORY_ID` selects LangGraph's thread saver only. Durable session events stay on `agentcore-memory`.

# agentcore-memory

Short-term events and long-term records. See [the library design](../../docs/design/library.md). Version 0.1.0.

`MemoryClient` takes a `Guard`. `create_event` stores the sanitized text or raises `MemoryWriteDenied` and stores nothing. `promote` copies one short-term event to long-term after a second screen. `list_session_events` is short-term, one session, one actor. `retrieve` is lexical (`method` is `lexical`) and does not return another actor's records.

The namespace is `{agent_version}/{environment}`. Memory writes go through this client after the guard. They do not go through Gateway. Gateway fronts tools and knowledge bases. This client does not call the AgentCore Memory service yet.

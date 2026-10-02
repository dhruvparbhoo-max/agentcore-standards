# agentcore-memory

Short-term events and long-term records (DESIGN §2.3, §2.8). Version 0.1.0.

`MemoryClient` takes a `Guard`. `create_event` stores the sanitized text or raises `MemoryWriteDenied` and stores nothing. `promote` copies one short-term event to long-term after a second screen. `list_session_events` is short-term, one session, one actor. `retrieve` is lexical (`method` is `lexical`) and does not return another actor's records.

The namespace is `{agent_version}/{environment}`. DESIGN §7 is still open on Gateway versus the Memory SDK. This client is the contract. It does not call the service.

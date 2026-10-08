# Memory overview

`primitives/memory/` is a path stub (lane E). Build it after guardrails, on its own lease. This page is the acceptance bar for that lease. It does not add API, and it does not store anything.

Concepts distilled from `memory-system` in [bojieli/ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/main/skills/memory-system). Credit: [attribution](../attribution/bojieli-ai-agent-book.md). The normative sketch is DESIGN §2.3. Whether writes go through Gateway or the Memory SDK directly is still open (DESIGN §7).

## What goes where

| Kind | Store | Example |
| --- | --- | --- |
| This session's raw turns | Trajectory: spans, logs, harness evidence | Tool name, latency, error class |
| Facts about one user that should outlive the session | Memory, bound to `actorId` and a namespace | A stated preference, after a guardrail allows the write |
| Knowledge shared by every user | A retrieval shelf, if one is added later | A policy document |

Shared documents are not Memory. A session transcript is not long-term memory. The microVM disk is scratch (DESIGN §1.5).

## Levels to test, when the package exists

| Level | The eval shows |
| --- | --- |
| L1 | A fact the user just stated is stored and retrieved for that actor. |
| L2 | The fact is still there after the session ends, and two conflicting facts cause a question, not a guess. |
| L3 | An older fact changes a later action (a warning before the write). Optional until L1 and L2 are boring. |

Cross-actor reads fail. A blocked guardrail prevents the write. Retrieval carries provenance on the trace. Those are the DESIGN §2.3 tests. Namespaces are per agent and environment.

## Write path

`Guard.allow_memory_write` runs before `create_event`. Blocked content never reaches Memory or the user channel. `agentcore-guardrails` is a stub. The offline stand-in is `PatternGuard`: a memory event is allowed only when `event["guarded"]` is true. The real package implements the protocol. It does not copy the fixture list.

Extract facts after the turn, off the critical path. Keep them selective (drop "the search returned three rows"), abstracted (a one-time choice becomes a preference only when the evidence says so), and structured (fields you can retrieve). Merge and prune on a schedule. Redact before logs and before eval evidence. No secrets in Memory payloads (DESIGN §1.5).

Experience from production misses follows [the experience loop](../ops/experience-loop.md): a failing eval first. A remembered fact is not a substitute for that gate.

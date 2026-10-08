# Pattern design outline

Every pattern has `docs/design.md`. Copy this outline. Fill it in for that pattern. Link to [library.md](library.md) for a shared rule. Do not paste the library page, and do not invent a second rule for queues, retries, approvals, releases, images, or the front door.

Write plain sentences. Define a term the first time you use it. Say when a number is an assumption because the pattern has no traffic yet.

The twelve-item kit (README, `pattern.yaml`, prompts, Cedar, approvals, tracing, tests, golden set, events, untrusted-input handling, limits, CDK deploy and teardown) is specified in the library page. This design page explains the behaviour. It does not replace those files.

Start the page with a short card:

- Pattern name and folder.
- Owner.
- Autonomy (`observer`, `assistant`, `autonomous`, or `orchestrator`) and risk tier.
- Framework (`create_agent`, `strands`, or `harness`) and trigger (`none`, `event`, or `schedule`).
- `deployment: docker`, and the image this pattern owns (the agent image, plus any Gateway tool image that ships with it).
- Who the agent acts as (`user` or `service`).
- Session lifetime: chat defaults (5 minutes idle, 30 minutes maximum) or the background values, with the reason if they differ.

Then these sections, in this order, with these headings.

## Main flow and where state lives

Describe the happy path from the first input to the answer or the side effect. The first hop is the front door. Name each later hop (person, event, queue, agent, Gateway target, approver) in order.

Say where each piece of state is stored. Use the library stores: job row, agent memory, knowledge base, microVM scratch, traces, audit. For this pattern, say which of those it actually uses. A chat pattern with `trigger: none` still says that it has no job row. A retrieval pattern says that documents live in a knowledge base behind a Gateway target, with the tenant and role filter taken from the verified login. It does not add a custom search tool.

If `lifecycle.resumable` is true, say what the checkpoint contains and which step writes it. If the pattern can pause for a person, say that the waiting flag is on the job row, not in the session.

Say how a developer runs this locally: Docker Compose, the sample events, and `make local`, before any deploy.

## Failure handling

Cover all four cases. A missing case is an incomplete design.

### Duplicate events

Say which idempotency key this pattern uses (source plus event id, or the reason there is no event). Say what the user sees when the same event arrives twice. Say which tool keys protect send, spend, delete, and change.

### Retries and timeouts

List the faults this pattern treats as retryable and the faults it treats as fatal. Point at `lifecycle.max_steps`, `lifecycle.timeout_s`, and `lifecycle.max_retries`. Say what the user or the job status shows when a cap is hit. Say which model is primary and which is the fallback. Say the idle and maximum session times, and that a second call on the same session does not run beside the first.

### Stuck approval

If this pattern can send, spend, delete, or change, say how long the token lives, how many people must approve, and what the sweeper does at expiry. Say how a new session resumes from the checkpoint after the microVM has gone. The resume goes through the front door. If this pattern cannot do those actions, say that in one sentence and leave the mechanism to the library page.

### Other failures worth naming

Add only the failures that are special to this pattern. Examples: retrieval returns nothing, a tool schema rejects the arguments, the kill switch for this agent is off, a quota is spent. Say the user-visible result for each one. For a retrieval pattern, the empty result is the sentence "I couldn't find this in the policies".

## Expected load and cost

Say what a normal day looks like: requests or events, model calls per job, and tools per job. If you have no measurement, label the numbers as the design assumption.

Repeat the caps from `pattern.yaml`: `cost.max_usd_per_run`, `cost.monthly_cap_usd`, and `cost.on_cap`. Say what pauses when the monthly cap is hit. The front door also enforces the user and team quotas. Say which of those this pattern expects to hit first.

Note anything that makes this pattern expensive (long retrieval, many agent hops, approval waits that hold a session). Do not hold a session open while a person decides. That cost belongs to the job row, not to a live microVM.

## Session budget

Every design page has this section.

A pattern with one agent writes one sentence: it uses one session per conversation, and it does not start specialist sessions.

A pattern that starts more than one agent counts sessions, not requests. Write the agents per conversation, the expected arrivals, and the session lifetime. Multiply them and compare the product with the region's session quota. Say what changes if the product would exceed the quota (a shorter idle timeout, fewer specialists, or a different pattern). One conversation a minute can hold many specialist microVMs at once, because each one stays up until it times out. That is why this section exists.

## Security and trust boundaries

Say who the agent acts as, and which systems it calls. For `acts_as: user`, name the on-behalf-of scopes. For `acts_as: service`, say whose consent was stored and where that record lives.

Say that the Runtime role holds only what that user may access, because a session can read its own credentials.

List untrusted inputs (user text, documents, tool results, events, other agents). Say that they are tagged and guarded before the model sees them.

Name the Cedar file and the Agent Registry tools it allows. If the pattern retrieves documents, name the Gateway knowledge-base target and the filter taken from the verified login. Point at `output_schema`. Say whether personal data can appear, the data region, and what is masked in logs and memory.

Say which actions write an audit record. The front door already writes one entry per call. Say what this pattern adds for send, spend, delete, or change. Say which secrets the pattern reads, by name only, from Secrets Manager.

Say what the kill switch does to this pattern (per agent, and per tool). Name the session header (`X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`, or `Mcp-Session-Id` when the protocol is MCP) and say the header allowlist is in the CDK input.

If the pattern runs code the model wrote, say that it uses Code Interpreter in VPC mode, with a DNS firewall, and with IMDSv2 required. If it does not run that code, say so in one sentence.

## When to pick a different pattern

Give concrete limits, each as its own sentence.

- Use a workflow, not this agent, when the steps never change and a model is not choosing among them.
- Use `framework: harness` when the pattern is config, tools, and a prompt, and it does not need its own loop code. Use `create_agent` or `strands` when it does.
- Name the sibling pattern a reader should open instead, and the condition that makes it a better fit. For example, a policy question that must send an email belongs with the pattern that pauses for approval, not with a read-only Q&A.
- Say the load, the data class, or the autonomy level this pattern refuses. A read-only assistant does not become an orchestrator by editing `pattern.yaml` alone. That change needs a new design page.

End with the golden-set cases that prove the limits: the empty-retrieval sentence, the duplicate event, the expired approval, and the cap that stops the loop. A retrieval pattern also points at the source-backed score (pass at 0.7) and the goal-success cases on the messy fake policies. Point at the files. Do not paste the cases.

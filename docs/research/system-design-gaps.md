# System design gaps for the AgentCore pattern library

Written 9 Oct 2026 for Dhruv's AI innovation team. Every URL below was fetched or seen in search results during this research. Dates are publication dates where the page shows one.

## Summary

The plan already covers a lot: folder layout, a 12-item kit for every agent, design pages, memory, and approvals. What it mostly misses is how agents run as a live service over time. The biggest holes are who the agent acts as when it calls other systems, what happens to a long task when its session dies, how to stop a misbehaving agent quickly, and how model calls survive throttling or an outage. Privacy (PII in logs and memory), audit records, and checking model output before acting on it are also missing. Most of the rest can wait until the first three patterns work.

I found 24 gaps. Nine are "now" because the first three patterns (chat, ambient, human approval) need them or because they are cheap to add while the primitives are being built. Eleven are "soon" and four are "later", and the last of those groups five smaller items.

## Step 1. My own checklist (first principles)

I wrote this before reading the sources, then ticked off what the plan covers.

Classic distributed systems

| Area | Covered by the plan? |
| --- | --- |
| Main request flow and where state lives | Yes (design page) |
| Idempotency and duplicate events | Yes (library page, design page) |
| Retries, timeouts, backoff | Partly. Per agent yes, but not for model throttling |
| Queues and async jobs | Yes (triggers primitive, job queueing page) |
| Long-running work, checkpoints and resume | No |
| Backpressure and rate limits at the front door | No |
| Dependency failure and fallbacks (model, tools) | No |
| Streaming and progress updates | No |
| Authentication of users | Yes (Cognito) |
| Authorisation of what the agent does on a user's behalf | No |
| Secrets | Yes (Secrets Manager) |
| Audit trail | No (tracing is not an audit record) |
| Data classification, PII, residency, log retention | No (only memory retention) |
| Environments and accounts (dev, staging, prod) | No |
| Deployment strategy and in-flight work during deploys | Partly (versioning and rollback named only) |
| SLOs, alerts, dashboards | No |
| Incident response, runbooks, kill switch | No |
| Cost tracking and budgets across agents | Partly (per-run limits only) |
| Backup and disaster recovery | No |
| Multi-tenancy and noisy neighbours | No |
| Accessibility of the UI | No |

Agent-specific

| Area | Covered by the plan? |
| --- | --- |
| Prompt injection from outside text | Yes (untrusted tagging, guardrails) |
| Tool limits | Yes (Cedar) |
| Human approval on risky actions | Yes |
| Tracing of reasoning and tool calls | Yes |
| Evals and golden sets | Yes |
| Memory types, scope, retention | Yes |
| Memory poisoning (bad facts written to memory) | No |
| Context window limits and compaction | No |
| Model choice, fallback, retirement | No (prompt caching parked) |
| Checking model output before acting on it | No |
| Prompt, model, tool and policy versioned as one release | No |
| Tool and MCP server supply chain | No |
| Tool contract versioning | No |
| Agent-to-agent trust and cascading failures | Partly (call pattern only, not trust) |
| Approver fatigue and approval screen quality | No |
| Red teaming and security tests in CI | No |
| User feedback flowing back into evals | No |
| Ownership, autonomy level, sign-off to ship | No |
| Agent registry and retiring old agents | No |
| Knowledge freshness for retrieval | No |
| Sandboxed code execution | No |
| "Do you need an agent at all" guidance | No |

## Step 2. Sources read

AWS
- AWS Well-Architected Agentic AI Lens, published 10 Jun 2026. https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/agentic-ai-lens.html
- Agentic AI Lens design principles. https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/design-principles.html
- Agentic AI Lens Appendix A, all 150 best practices by ID. https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/appendix-a.html
- Agentic AI Lens AGENTSEC08-BP01, input validation and prompt injection. https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/agentsec08-bp01.html
- Updated Generative AI Lens announcement. https://aws.amazon.com/blogs/architecture/announcing-the-updated-aws-well-architected-generative-ai-lens/
- Prescriptive Guidance, Operationalizing agentic AI on AWS. https://docs.aws.amazon.com/prescriptive-guidance/latest/strategy-operationalizing-agentic-ai/introduction.html
- Prescriptive Guidance, Enterprise multi-account architecture for agentic AI. https://docs.aws.amazon.com/prescriptive-guidance/latest/agent-ops-maturity-roadmap-for-enterprise-ai/introduction.html and platform operations page https://docs.aws.amazon.com/prescriptive-guidance/latest/agent-ops-maturity-roadmap-for-enterprise-ai/platform-operations.html
- Prescriptive Guidance, Multi-tenant agentic AI, enforcing tenant isolation. https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-multitenant/enforcing-tenant-isolation.html
- AgentCore Identity, on-behalf-of token exchange. https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/on-behalf-of-token-exchange.html
- AgentCore Identity, workload access tokens. https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/get-workload-access-token.html
- AgentCore Runtime inbound and outbound auth. https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-oauth.html
- AgentCore Runtime sessions. https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html
- AgentCore Runtime lifecycle settings. https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html
- AgentCore Runtime troubleshooting (ping and HealthyBusy). https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-troubleshooting.html
- AgentCore Runtime versioning and endpoints. https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html
- AgentCore Policy generally available, Mar 2026. https://aws.amazon.com/about-aws/whats-new/2026/03/policy-amazon-bedrock-agentcore-generally-available/
- AgentCore Observability setup. https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html
- AWS Agent Registry generally available, Aug 2026. https://aws.amazon.com/about-aws/whats-new/2026/08/aws-agent-registry-generally-available/ and docs https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry.html
- Implementing resilience patterns with Amazon Bedrock and LLM gateway, 30 Jun 2026. https://aws.amazon.com/blogs/machine-learning/implementing-resilience-patterns-with-amazon-bedrock-and-llm-gateway/
- Bedrock cross-Region inference. https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html and geographic profiles https://docs.aws.amazon.com/bedrock/latest/userguide/geographic-cross-region-inference.html
- Bedrock model lifecycle. https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle.html
- Bedrock Guardrails sensitive information filters. https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-sensitive-filters.html
- Bedrock Guardrails InvokeGuardrailChecks for agents. https://aws.amazon.com/blogs/machine-learning/safeguard-your-agentic-ai-applications-with-the-amazon-bedrock-guardrails-invokeguardrailchecks-api/

Other
- Anthropic, Building effective agents, 19 Dec 2024. https://www.anthropic.com/engineering/building-effective-agents
- Anthropic, How we built our multi-agent research system, 13 Jun 2025. https://www.anthropic.com/engineering/multi-agent-research-system
- Anthropic, Effective context engineering for AI agents, 29 Sep 2025. https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- OpenAI, A practical guide to building agents. https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/
- Google, Introduction to Agents whitepaper (Kaggle, Nov 2025). https://www.kaggle.com/whitepaper-introduction-to-agents
- OWASP Top 10 for Agentic Applications 2026, 9 Dec 2025. https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/
- OWASP Top 10 for LLM Applications 2025 (LLM05 improper output handling, LLM10 unbounded consumption). https://owasp.org/www-project-top-10-for-large-language-model-applications/2_0_vulns/LLM05_ImproperOutputHandling and https://owasp.org/www-project-top-10-for-large-language-model-applications/2_0_vulns/LLM10_UnboundedConsumption
- NIST AI 600-1, Generative AI Profile. https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence
- MCP security best practices (spec 2025-06-18). https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices
- 12-factor agents, HumanLayer. https://github.com/humanlayer/12-factor-agents
- W3C WCAG 2.2. https://www.w3.org/WAI/standards-guidelines/wcag/

What the six sample repos already have that we can reuse (from a quick search of the cloned repos in /workspace/aws-refarch):
- FAST has a context management guide (docs/CONTEXT_MANAGEMENT.md), AgentCore Memory as a LangGraph checkpointer, AG-UI streaming over SSE, and uses the token vault for the runtime's own Gateway credentials. It does not use on-behalf-of user tokens.
- The ambient repo fails closed if no guardrail is set, wraps outside text in `<untrusted_*>` tags, caps iterations, and has a per-session circuit breaker. Its threat model is the best starting point for the security parts below.
- Social intelligence has an HTTP helper with retries, a per-host circuit breaker and an outbound allow-list against SSRF. It notes that moving its API keys into the AgentCore token vault is future work.
- None of the six has model fallback, a kill switch, an audit store separate from logs, PII masking on tool output, or multi-account promotion.

## Step 3. Gaps

Each gap says what it is, why it matters for agents, where it lives in the repo, the priority, and one source.

### Now

**1. Agent identity and acting on a user's behalf**
What: Decide who the agent is when it calls another system. It should be either itself (a service identity) or the signed-in user, using a short-lived token scoped to that user and that tool. The agent's permissions and the user's permissions are kept separate.
Why for agents: An agent with one broad service key can do anything for anyone, and a prompt injection then gets all of that power. The on-behalf-of flow means a tool call can never do more than the user could do themselves.
Where: Extend `primitives/auth/` into `primitives/identity/` (inbound Cognito, outbound token vault, on-behalf-of exchange). Add an `identity:` block to `pattern.yaml` with `acts_as: user | service` and the scopes per tool. Add trust boundaries to each design page.
Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/on-behalf-of-token-exchange.html (also OWASP ASI03).
Note: background agents have no live user token. The design page should say which identity they use and how a user's consent is stored for later.

**2. Long-running work: checkpoints and resume**
What: Save the agent's progress after each step so work can pick up where it stopped, rather than starting again.
Why for agents: AgentCore microVM sessions stop after 15 minutes idle (by default) or 8 hours total, and in-memory and disk state is lost unless session storage is set up. A human approval that waits overnight, or an ambient job that runs long, will lose its place. Restarting is costly and may repeat side effects.
Where: `primitives/state/` (checkpointer on AgentCore Memory or DynamoDB), a `lifecycle:` block in `pattern.yaml` (idle timeout, max lifetime, resumable yes or no), and a section in the ambient and human-approval design pages. The ping handler must report HealthyBusy during background work.
Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-sessions.html

**3. Kill switch and break-glass runbook**
What: A quick, tested way to stop one agent, one tool, or all agents, plus a short written runbook for what to do when an agent misbehaves.
Why for agents: Agents act on their own and can loop, spend or send at machine speed. When one goes wrong, you need to stop it in minutes, without a redeploy.
Where: `primitives/controls/` (a feature flag per agent and per tool read on every step, a Cedar forbid policy switched to ENFORCE, and a script that calls StopRuntimeSession). Put runbooks in `docs/runbooks/`. CI checks that every pattern reads the flag.
Source: https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/appendix-a.html (AGENTOPS07-BP04 break-glass runbooks, AGENTSEC07-BP04 agent containment).

**4. Model access layer: throttling, fallback and region**
What: One shared way to call models that handles throttling with backoff, uses a cross-Region inference profile, can fall back to a second model, and has rate limits at the front door.
Why for agents: One task makes many model calls, so a short throttle or outage breaks the whole task, not one reply. AWS says cross-Region inference adds capacity but is not failover. A UK team also needs the EU or UK geographic profile so data stays in the right place.
Where: `primitives/model/`. This is the same shared model setup where prompt caching will go later, so build the wrapper now and leave caching parked. Add `model.primary`, `model.fallback` and `model.region_profile` to `pattern.yaml`.
Source: https://aws.amazon.com/blogs/machine-learning/implementing-resilience-patterns-with-amazon-bedrock-and-llm-gateway/

**5. Context window management**
What: Rules for what goes into the model's context each turn, such as clearing old tool results, summarising long histories (compaction) and handing big searches to sub-agents that return short summaries.
Why for agents: Context fills up with every tool call. Past a point, quality drops ("context rot"), costs climb and the run eventually fails at the limit. This is a different problem from long-term memory.
Where: `primitives/context/`, a `context:` block in `pattern.yaml` (token budget, compaction trigger, tool-result clearing on or off), and an eval case with a long conversation. FAST's CONTEXT_MANAGEMENT.md is a good start.
Source: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents

**6. Checking model output before acting on it**
What: Treat the model's output as untrusted. Check it against a schema and business rules before it becomes a tool call, a database write or something shown in the UI.
Why for agents: The model's output drives real actions. A bad field, wrong ID or injected HTML can turn into a wrong payment, a wrong email or an XSS bug. Cedar limits which tool is called but doesn't check every argument.
Where: `primitives/validation/` (structured output with Pydantic or JSON Schema, argument checks inside each Gateway tool), and an `output_schema` field in `pattern.yaml`. The contract tests already planned can use the same schema.
Source: https://owasp.org/www-project-top-10-for-large-language-model-applications/2_0_vulns/LLM05_ImproperOutputHandling

**7. Audit trail separate from tracing**
What: A permanent, tamper-resistant record of who asked for what, what the agent decided, which tools it called with which inputs, and who approved it.
Why for agents: Traces are for debugging and are sampled and deleted. When an agent sends or changes something, you need to show later who was responsible. That matters most for human-approval decisions.
Where: `primitives/audit/` (write-once store, such as S3 with Object Lock or a DynamoDB table with no delete rights), written by the approvals primitive and the Gateway. Retention goes in the library-wide design page.
Source: https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/appendix-a.html (AGENTOPS05-BP03 and AGENTSEC05-BP01).

**8. Data privacy: PII, logs and residency**
What: Label what kind of data each agent touches, mask personal data in tool results, memory writes and logs, and set where data is processed and how long logs and traces are kept.
Why for agents: Agents pull personal data from tools and copy it into prompts, memory, traces and model invocation logs. AWS notes that guardrails don't mask PII in tool arguments or results, and invocation logs can keep the unmasked text. Under UK GDPR that is a real exposure.
Where: `primitives/privacy/` (guardrail sensitive-information filter applied to tool results and memory writes, log redaction), plus a `data:` block in `pattern.yaml` (data class, PII yes or no, region, log retention). Add a privacy line to each design page.
Source: https://docs.aws.amazon.com/bedrock/latest/userguide/guardrails-sensitive-filters.html

**9. Checking what gets written to memory**
What: Validate and filter facts before they are saved to long-term memory, record where each memory came from, and give users a way to see and delete them.
Why for agents: One injected or wrong "fact" saved to memory steers every later run for that user or team. This is OWASP's memory and context poisoning risk. It's cheap to add while the memory primitive is being built.
Where: Inside `primitives/memory/` (a write filter, source tags, a delete path), plus a `memory.write_policy` field in `pattern.yaml`.
Source: https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/ (ASI06), and the Agentic AI Lens AGENTSEC01-BP02.

### Soon

**10. Release bundle: prompt, model, tools and policy versioned together**
What: Treat each agent's prompt files, model ID, tool list and Cedar policies as one versioned release. Record that version on every run so you can replay a run and roll back.
Why for agents: Agent behaviour changes when any one of these changes, not only the code. Without one version you can't tell which change broke quality. Long sessions may still be running the old version during a deploy.
Where: Generate a release ID in CI and stamp it on traces. Pin a named AgentCore endpoint per environment (DEFAULT always moves to the newest version), and roll back by moving the endpoint. Add a section on in-flight sessions during deploys to the library-wide design page.
Source: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html

**11. Environments, accounts and promotion**
What: Separate dev, staging and prod (ideally separate AWS accounts), build the container once, and promote that same image with an eval gate and a manual approval before prod.
Why for agents: Agents are judged by evals rather than unit tests alone, so the gate has to be an eval score. Separate accounts also give separate model quotas and limit the damage a bad agent can do.
Where: `infra/` (environment config), `.github/workflows/` (promotion steps), and the library-wide design page.
Source: https://docs.aws.amazon.com/prescriptive-guidance/latest/agent-ops-maturity-roadmap-for-enterprise-ai/introduction.html

**12. SLOs, dashboards and alerts**
What: Targets for each pattern (task success rate, time to first token, cost per task, approval wait time, error rate) and alarms when they slip.
Why for agents: An agent can be "up" while doing the wrong thing. You need quality and cost signals, not only uptime.
Where: An `slo:` block in `pattern.yaml`, a CloudWatch dashboard construct in `infra/constructs/`, and alarms that link to the runbooks.
Source: https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/appendix-a.html (AGENTOPS05-BP04 KPIs and BP05 dashboards).

**13. Cost tracking and budget cut-offs across agents**
What: Tag every model and tool call with agent, pattern, user and environment, add budgets that alert and then stop spending, and flag unusual spending patterns.
Why for agents: Per-run limits stop one loop, but not 500 runs triggered by a noisy event source. Multi-agent setups can use about 15 times the tokens of a chat, so costs need tracking at the agent level.
Where: Cost tags in `primitives/tracing/`, a budget construct in `infra/constructs/`, a `cost:` block in `pattern.yaml` (monthly cap, action when hit).
Source: https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/appendix-a.html (AGENTCOST05 attribution, AGENTCOST07-BP01 automated cutoffs).

**14. Streaming and progress updates**
What: Stream answers as they're written and send progress events ("searching", "waiting for approval") for long tasks, with a job status the UI can poll.
Why for agents: Agent tasks take seconds to hours. Without progress, people think it has hung and retry, which creates duplicate work.
Where: The shared frontend shell and a small event contract in `primitives/` (FAST's AG-UI over SSE is a good base). Add a `ux.streaming` field in `pattern.yaml`.
Source: https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/appendix-a.html (AGENTPERF02-BP04).

**15. Tool and MCP supply chain**
What: Keep a list of approved tools and MCP servers, pin their versions, review tool descriptions as carefully as code, request the fewest scopes, never pass the user's token straight through, and limit where tools can make outbound calls.
Why for agents: The model trusts tool descriptions and tool results. A changed or malicious MCP server can redirect the agent or leak data. Cedar controls which tool is called but not what the tool itself does.
Where: `primitives/gateway-tools/` (allow-list, pinned versions, egress allow-list like social intelligence's `_http.py`), and a CI check that flags tool description changes for review.
Source: https://modelcontextprotocol.io/specification/2025-06-18/basic/security_best_practices (also OWASP ASI04).

**16. Tool contract versioning**
What: Give every tool a versioned input and output schema, keep old versions working for a while, and run contract tests between agent and tool.
Why for agents: If a tool's output shape changes, the model may still "succeed" and quietly make things up. That failure doesn't show up as an error.
Where: `primitives/gateway-tools/` (schema per tool with a version), contract tests in CI, and tool versions listed in `pattern.yaml`.
Source: https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/design-principles.html ("ground autonomous behavior in explicit contracts").

**17. Agent-to-agent trust and stopping failures from spreading**
What: Authenticate every call between agents, check what one agent passes to another, and add circuit breakers and limits so one failing agent doesn't drag down the rest.
Why for agents: In a team of agents, one hijacked or confused agent can pass bad instructions downstream, and one slow agent can block the orchestrator. The library page covers how agents call each other but not whether they trust each other.
Where: The library-wide design page, plus `patterns/multi-agent-graph/` and `patterns/multi-agent-a2a/` (signed or IAM-authenticated calls, per-hop timeouts, circuit breakers).
Source: https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/ (ASI07 and ASI08), Agentic AI Lens AGENTSEC06.

**18. Approval screen quality and approver fatigue**
What: Design approvals so people actually read them. Show a clear diff of what will happen, the risk level and the agent's confidence, batch low-risk items, and require two people for the riskiest actions.
Why for agents: If approvals are frequent and vague, people click yes without reading, and the safety step stops working. Attackers can also word a request so it looks harmless.
Where: `primitives/approvals/` and the frontend approval screen, plus `approval.risk_tier` and `approval.reviewers` fields in `pattern.yaml`.
Source: https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/appendix-a.html (AGENTSEC07-BP01 to BP03), OWASP ASI09.

**19. Security tests and red teaming**
What: A set of known attack prompts (injected instructions in files, emails and tool output) run in CI against every pattern, plus a red-team review before a pattern is marked ready.
Why for agents: Guardrails and tags reduce injection but don't remove it, as the ambient repo's threat model says. You need tests that prove the defences still work after each change.
Where: `eval/` gets an attack set next to the golden set, and CI runs it. Add a threat model per pattern, using the ambient repo's THREAT_MODEL.md as the template.
Source: https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/agentsec08-bp01.html

**20. Ownership, autonomy level and sign-off to ship**
What: Every agent has a named owner, an autonomy level (observer, assistant, autonomous, orchestrator) and a risk tier, and a short sign-off before it goes to prod.
Why for agents: Autonomy is the main risk lever. Writing it down makes the approval and testing depth match the risk, and someone is answerable when it goes wrong.
Where: `owner`, `autonomy` and `risk_tier` fields in `pattern.yaml`, a sign-off checklist in `docs/`, and a CI check that the fields exist.
Source: https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/design-principles.html (autonomy levels), NIST AI 600-1 for the wider risk list.

### Later

**21. User and approver feedback into evals**
What: Capture thumbs up or down, corrections and rejected approvals, and turn them into new eval cases.
Why for agents: Real failures are the best test cases, and approvals already give you a labelled yes or no for free.
Where: `primitives/eval/` (feedback store and import script) and the frontend.
Source: https://docs.aws.amazon.com/wellarchitected/latest/agentic-ai-lens/appendix-a.html (AGENTOPS02-BP04 feedback loops).
Note: this could move up to "soon" once the parked model-testing work starts, since they fit together.

**22. Multi-tenancy and noisy neighbours**
What: If the library is used by other teams or customers, pass a tenant ID through identity, memory, tools and data, and give each tenant its own rate limits.
Why for agents: One tenant's agent must never read another's memory or knowledge base, and one heavy user shouldn't use up the shared model quota.
Where: Tenant context in `primitives/identity/` and `primitives/memory/`, and per-tenant limits in `primitives/model/`.
Source: https://docs.aws.amazon.com/prescriptive-guidance/latest/agentic-ai-multitenant/enforcing-tenant-isolation.html

**23. Agent registry, model retirement and clearing out old agents**
What: List every deployed agent and tool in one catalogue (AWS Agent Registry went GA in Aug 2026), track when each model will be retired, and remove agents nobody uses.
Why for agents: Teams create agents quickly and forget them. Bedrock models move to Legacy and then end of life, at which point calls fail.
Where: `docs/catalog.md` can feed the registry later. Add a CI job that checks each pattern's model lifecycle status.
Source: https://aws.amazon.com/about-aws/whats-new/2026/08/aws-agent-registry-generally-available/ and https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle.html

**24. Smaller items: knowledge freshness, code sandbox, backup, accessibility and "do you need an agent"**
- Knowledge freshness. When a retrieval pattern is added, set a re-index schedule and show source dates so the agent doesn't answer from stale documents. Source: Agentic AI Lens AGENTREL05-BP03 (appendix link above).
- Code sandbox. If an agent ever runs code it wrote, run it in AgentCore Code Interpreter with outbound network blocked. Source: OWASP ASI05 (OWASP link above).
- Backup and recovery. Turn on point-in-time recovery for DynamoDB job and state tables, and write down what happens if a Region or AgentCore Memory is unavailable. Source: Agentic AI Lens AGENTREL03-BP02.
- Accessibility. Build the shared UI shell to WCAG 2.2 AA from the start, since approvals will be used by many people. Source: https://www.w3.org/WAI/standards-guidelines/wcag/
- Do you need an agent at all. Add a first question to `docs/catalog.md`: if the steps are fixed, use a plain workflow (Step Functions) and call the model only where needed. Source: https://www.anthropic.com/engineering/building-effective-agents

## What I'd fix first

1. Agent identity and acting on a user's behalf (gap 1). Every pattern that touches email, files or calendars needs it, and it's hard to retrofit once tools assume a shared service key.
2. Checkpoints and resume (gap 2). The human-approval and ambient patterns are in the first three, and both will hit the 15-minute idle and 8-hour session limits.
3. Model access layer (gap 4). Throttling is the most likely day-one failure, and the same wrapper is where caching, fallback, region and cost tags will all live.
4. Kill switch and runbook (gap 3). It's small to build, and it's what makes it safe to leave an ambient agent running.
5. Privacy and audit together (gaps 7 and 8). Logs and traces already capture prompts and tool results, so PII is being stored from the first deploy unless masking and retention are set up front.

## Suggested pattern.yaml additions (for reference)

```yaml
owner: team-member@example.com
autonomy: assistant            # observer | assistant | autonomous | orchestrator
risk_tier: medium
identity:
  acts_as: user                # user | service
  scopes: {calendar: [read], gmail: [draft]}
model:
  primary: eu.anthropic.claude-...   # geographic inference profile
  fallback: eu.amazon.nova-...
lifecycle:
  idle_timeout_s: 900
  max_lifetime_s: 28800
  resumable: true
context:
  token_budget: 120000
  compaction_at: 100000
  clear_tool_results: true
output_schema: schemas/answer.json
memory:
  write_policy: validated      # validated | off
data:
  classification: internal
  pii: true
  region: eu-west-2
  log_retention_days: 90
slo: {task_success: 0.9, p95_first_token_s: 3, cost_per_task_usd: 0.20}
cost: {monthly_cap_usd: 200, on_cap: pause}
approval: {risk_tier: high, reviewers: 1}
ux: {streaming: true}
```

# Prompt caching and agent testing on AWS

Research for the AgentCore pattern library. Written 9 Oct 2026. Every URL below was fetched or seen in search results during this research.

## 1. Prompt caching

### How it works

Prompt caching lets Bedrock reuse the work it already did on the start of a prompt. You mark the end of the part that doesn't change with a cache checkpoint. In the Converse API this is a separate `{"cachePoint": {"type": "default"}}` block placed right after the content you want cached. The first call writes that prefix to the cache. Any later call whose prompt starts with the exact same bytes reads it back, so you pay less for those tokens and the first token comes back sooner. The match is a strict prefix match. If one character changes before the checkpoint (a timestamp, a reordered tool, a different user name), the cache misses and you pay for a new write.

Bedrock reads the request in a fixed order: tools first, then system, then messages. Changing the tools list breaks the cache for the system prompt and messages too. So the rule is stable content first (tools, then system prompt, then fixed reference docs) and changing content last (the latest user turn, retrieved chunks, dates).

The cache is scoped to one AWS account and one Region. Cross-region inference profiles can cause extra cache writes when traffic moves between Regions. Caching only works on on-demand inference, not batch.

Bedrock now has two kinds. Implicit caching happens on its own for some models (Claude, Nova, OpenAI) and is best effort. Explicit caching uses checkpoints and gives you control. Claude also has "simplified" caching: one checkpoint at the end of the static part, and Bedrock looks back about 20 content blocks for the longest prefix it already has.

You can check it worked from the response. `cacheWriteInputTokens` above zero means a write, `cacheReadInputTokens` above zero means a hit, and both at zero means the prefix was too short or the model doesn't support it. Total input is `inputTokens + cacheReadInputTokens + cacheWriteInputTokens`.

Sources:
- Bedrock user guide, prompt caching (fetched): https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html
- AWS blog "Optimizing cost and latency with Amazon Bedrock prompt caching", 15 Sep 2026 (fetched): https://aws.amazon.com/blogs/machine-learning/optimizing-cost-and-latency-with-amazon-bedrock-prompt-caching/

### Key numbers

| Item | Value | Source |
|---|---|---|
| Checkpoints per request | Up to 4 (Claude, Nova). OpenAI GPT-5.6 and later: up to 4 cache writes | Bedrock user guide |
| Minimum tokens before a checkpoint | 512 (Claude 5 and 5.x family), 1,024 (Sonnet 4.5, 4.6, 5, 3.7, Opus 4.8), 4,096 (Opus 4.5, 4.6, 4.7 and Haiku 4.5), about 1K for Nova. Counted across tools + system + messages together. Below the minimum the call still works but nothing is cached | Bedrock user guide |
| Nova cache limit | 20K tokens max; Nova can't put checkpoints in `tools` | Bedrock user guide |
| Default TTL | 5 minutes, reset on every hit | Bedrock user guide |
| 1-hour TTL | Yes. Launched 26 Jan 2026 for Sonnet 4.5, Haiku 4.5, Opus 4.5; now on all current Claude models (4.5 and later). Set `"ttl": "1h"` in `cachePoint`. Longer TTL checkpoints must come before shorter ones. Sending `ttl` to a 5-minute-only model can return a ValidationException | What's New, 26 Jan 2026: https://aws.amazon.com/about-aws/whats-new/2026/01/amazon-bedrock-one-hour-duration-prompt-caching/ and the user guide |
| OpenAI on Bedrock | GPT-5.6 and later: explicit breakpoints via `prompt_cache_breakpoint`, 30-minute minimum TTL, not through Converse | Bedrock user guide; AWS blog on GPT-5.6 explicit caching (seen in results): https://aws.amazon.com/blogs/machine-learning/introducing-explicit-prompt-caching-for-openai-gpt-5-6-models-on-amazon-bedrock/ |
| Write price | 1.25x normal input price (5-minute cache), 2x (1-hour cache) | AWS blog 15 Sep 2026 |
| Read price | 0.1x normal input price (90% off). Anthropic lists 0.05x for Opus 5.5 and Sonnet 5.5; check the Bedrock pricing page for those | AWS blog 15 Sep 2026; Anthropic pricing page (seen in results): https://platform.claude.com/docs/en/about-claude/pricing |
| Break-even | A 5-minute write pays for itself after 1 read; a 1-hour write after 2 reads | Anthropic pricing page |
| Worked saving | One 10,000-token document with 10 questions saves about 75% of input cost | AWS blog 15 Sep 2026 |
| Headline claims | Up to 90% lower cost and up to 85% lower latency | Product page (seen in results): https://aws.amazon.com/bedrock/prompt-caching/ |
| Latency in practice | TTFT gains are small for 2K to 5K token prefixes and clearer above 10K tokens | AWS blog 15 Sep 2026 |
| Rate limits | Cache hits don't count against the tokens-per-minute quota | Bedrock user guide |

### Framework support

Strands Agents. `BedrockModel(cache_config=CacheConfig(strategy="auto"))` caches the system prompt, the tool definitions and the conversation. Each part has its own TTL switch: `tools_ttl`, `system_prompt_ttl`, `messages_ttl`. For example `CacheConfig(ttl="1h", messages_ttl="5m")` holds tools and system for an hour and the conversation for five minutes. The older `cache_tools` parameter is deprecated in favour of `tools_ttl`. You can also place `SystemContentBlock(cachePoint={"type": "default"})` or a `cachePoint` block in a message by hand. Cache counts show up in `result.metrics.accumulated_usage` and in OpenTelemetry traces. Turn off `system_prompt_ttl` if the system prompt changes on every call, or you pay for writes that never get read. Summarising or editing old messages causes a miss.
- https://strandsagents.com/docs/user-guide/sdk/model-providers/amazon-bedrock-prompt-caching/ (fetched)

LangChain and LangGraph. `ChatBedrockConverse.create_cache_point()` adds the `cachePoint` block inside a message or a `ChatPromptTemplate`. Cache counts come back in `usage_metadata.input_token_details` as `cache_creation` and `cache_read`. The AWS blog uses `langchain-aws>=0.2.12` and boto3 1.43.0 or later for `ttl`.
- AWS blog 15 Sep 2026, scenario 6 (fetched).

AgentCore. Runtime doesn't add caching itself. It comes from the framework inside the container (Strands or LangGraph) calling Converse.

### Design rules

1. Order the prompt as tools, then system prompt, then fixed reference docs, then the conversation, then the new turn.
2. Keep dates, user names, request IDs and retrieved chunks out of the cached part. Put them after the last checkpoint.
3. Keep tool order and tool JSON stable. Sort tools by name so a new deploy doesn't reorder them.
4. Check the prompt is above the model's minimum. Opus 4.5/4.6 and Haiku 4.5 need 4,096 tokens, so a short system prompt on Haiku 4.5 is never cached.
5. Use 1-hour TTL for tools and system prompt when calls are more than 5 minutes apart (background agents, approval waits, scheduled jobs). Use 5 minutes for busy chat. Put the 1h checkpoint before the 5m one.
6. In a multi-tenant agent, add a tenant hash at the start of the cached text so tenants don't share entries (scenario 5 in the AWS blog).
7. Log cache reads and writes for every call. A high write count with few reads means the prefix keeps changing.

### Other cost features

- Intelligent prompt routing sends each prompt to one of two models in the same family based on predicted quality. Default routers use Nova and Llama. It only works well for English, can't learn from your own results, and adds a routing layer that makes caching and evals harder to reason about. Low priority for the library. Docs (fetched): https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-routing.html. AWS blog, 22 Apr 2025 (seen in results): https://aws.amazon.com/blogs/machine-learning/use-amazon-bedrock-intelligent-prompt-routing-for-cost-and-latency-benefits/
- Batch inference costs about 50% less than on-demand for supported models but has no prompt caching, so it suits offline eval runs, not live agents. Pricing page (seen in results): https://aws.eu/bedrock/pricing/

## 2. Testing and evaluation on AWS

### Managed options

| Option | What it does | Link |
|---|---|---|
| AgentCore Evaluations (GA March 2026) | Scores agent OpenTelemetry traces. 13 built-in LLM-judge evaluators across three levels. Session: GoalSuccessRate. Trace: Helpfulness, Correctness, Coherence, Conciseness, Faithfulness, Harmfulness, InstructionFollowing, ResponseRelevance, ContextRelevance, Refusal, Stereotyping. Tool: ToolSelectionAccuracy, ToolParameterAccuracy. There are also trajectory checks (ExactOrder, InOrder, AnyOrder) that use expected tool lists, plus skill evaluators. Custom LLM-judge evaluators, Lambda code evaluators, and DeepEval and AutoEval evaluators run as managed evaluators. Works with Strands and LangGraph. | Blog 31 Mar 2026 (fetched): https://aws.amazon.com/blogs/machine-learning/build-reliable-ai-agents-with-amazon-bedrock-agentcore-evaluations/ ; docs (fetched): https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/evaluations.html |
| AgentCore on-demand evaluation | The `Evaluate` API, called sync for CI and dev. It takes ground truth (`expectedResponse`, `assertions`, `expectedTrajectory`) and allows up to 10 evaluations per call. `OnDemandEvaluationDatasetRunner` runs a whole golden dataset against the agent. | API (seen in results): https://docs.aws.amazon.com/bedrock-agentcore/latest/APIReference/API_Evaluate.html ; dataset runner (seen in results): https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/dataset-evaluations-on-demand.html |
| AgentCore online evaluation | Samples live traffic at a rate you set, with up to 10 evaluators per config. Results land in CloudWatch, where you can set alarms. Ground truth isn't used here. | https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/create-online-evaluations.html (seen in results) |
| AgentCore batch evaluation | An async job that scores many sessions from CloudWatch Logs, for baselines and before/after checks. | CI blog below |
| Bedrock Evaluations, model eval | Compares models or prompts with automatic metrics, human reviewers, or LLM-as-a-judge. You can bring your own responses. | https://docs.aws.amazon.com/bedrock/latest/userguide/evaluation-judge.html (seen in results); GA blog 4 Apr 2025 (seen in results): https://aws.amazon.com/blogs/machine-learning/evaluate-models-or-rag-systems-using-amazon-bedrock-evaluations-now-generally-available/ |
| Bedrock Evaluations, RAG / Knowledge Base | Scores retrieve-only or retrieve-and-generate runs for context relevance, coverage, correctness, faithfulness and citations. Works with outside RAG systems too. | https://docs.aws.amazon.com/bedrock/latest/userguide/evaluation-kb.html (seen in results); blog 14 Mar 2025 (seen in results): https://aws.amazon.com/blogs/machine-learning/evaluating-rag-applications-with-amazon-bedrock-knowledge-base-evaluation/ |

### Open-source options

| Option | What it does | Link |
|---|---|---|
| Strands Evals SDK (`strands-agents-evals`, v1.5.0 on PyPI, 8 Oct 2026) | Code-first test cases and experiments. Includes OutputEvaluator (rubric judge), TrajectoryEvaluator (tool order with exact, in-order and any-order scorers), InteractionsEvaluator (multi-agent handoffs), a CLI for CI, and an experiment generator that makes test sets. | https://github.com/strands-agents/evals (seen in results); https://strandsagents.com/docs/user-guide/evals-sdk/quickstart/ (seen in results) |
| Ragas | RAG metrics such as faithfulness, answer relevance and context recall. AWS shows it with Langfuse for Bedrock Agents. | Blog 28 Apr 2025 (seen in results): https://aws.amazon.com/blogs/machine-learning/evaluate-amazon-bedrock-agents-with-ragas-and-llm-as-a-judge/ ; https://github.com/aws-samples/amazon-bedrock-agent-evaluation-framework |
| DeepEval | Its evaluators are now available as managed evaluators inside AgentCore Evaluations. | CI blog 8 Sep 2026 (fetched) |
| Langfuse / LangSmith | Tracing plus scoring dashboards. Langfuse is used in the AWS agent evaluation framework sample above. LangSmith is used for optional tracing in sample-ambient-agents-on-agentcore. | as above |
| promptfoo | Found in search but not in an AWS post I fetched. Fine for fast prompt checks, but not an AWS recommendation. | n/a |
| fmeval | AWS library for accuracy, toxicity and robustness on single model calls. Last release 1.2.3 in July 2025 and aimed at SageMaker. Not useful for agents. | https://github.com/aws/fmeval (seen in results) |

### How AWS says to test an agent

From the 31 Mar 2026 and 8 Sep 2026 AWS blogs:

1. Build a golden set of real requests with an expected answer, the expected tool list, and plain-English assertions about the outcome. Turn every production failure into a new case.
2. Score each level on its own: tool choice, tool parameters, answer quality and session goal. Fix tool selection before tool parameters.
3. Run each case more than once. AWS suggests at least 10 runs per question when benchmarking, because the same prompt can take different paths.
4. In CI, deploy to a dev stack, run the set, call the Evaluate API, and block the PR below a threshold (0.8 in the example). Leave some margin, since judge scores vary. A cheaper first step is to score stored trace fixtures without deploying (Approach A). Start with GoalSuccessRate, Correctness, ToolSelectionAccuracy and ToolParameterAccuracy, then add trajectory checks for tool-heavy agents and Harmfulness, Stereotyping and Refusal for agents that face customers.
5. Use Lambda code evaluators for exact checks (IDs, numbers, format). They're cheaper and repeatable.
6. In production, turn on online evaluation with sampling and add CloudWatch alarms on score drops. Compare against the CI baseline to spot drift.
7. Track cost and latency in AgentCore Observability next to quality. Evaluations only measure quality.

CI blog, 8 Sep 2026 (fetched): https://aws.amazon.com/blogs/machine-learning/automated-agent-evaluation-with-amazon-bedrock-agentcore-and-github-actions/
"Evaluate any agent framework with AgentCore Evaluations", 26 Aug 2026 (seen in results): https://aws.amazon.com/blogs/machine-learning/evaluate-any-agent-framework-with-amazon-bedrock-agentcore-evaluations/

## 3. What the six repos do

Searched with rg for cachePoint, cache_point, cache_prompt, cache_tools, CachePoint, prompt_cache, cache_config and "prompt caching", plus the eval terms.

Prompt caching: none of the six repos turns it on. The only cache reference is FAST's `docs/CONTEXT_MANAGEMENT.md` (line 381), which reads `cacheReadInputTokens` to estimate how full the context window is. It leaves out `cacheWriteInputTokens`, so it undercounts. Its summariser also rewrites old messages, which breaks a cached prefix.

| Repo | Caching | Testing and evals |
|---|---|---|
| fullstack-solution-template-for-agentcore (FAST) | None. Models: Sonnet 4.5, Opus 4.6 | `docs/AGENTCORE_EVALUATIONS_GUIDE.md` (1,317 lines) covers online and on-demand evals, the built-in evaluator reference, custom evaluators, CSV export, dashboards and AI-assisted prompt fixes. It's a guide only, with no eval code or golden set in the repo. `tests/unit`, `tests/integration` (including the live memory test), `infra-cdk/test`, `frontend/src/test`. CI does lint and security scans only. |
| guidance-for-multi-agent-orchestration... | None. Models: Haiku 4.5, Sonnet 4.5, 3.7 Sonnet | `tests/unit` and `tests/integration` (18 test files, including memory). No eval framework and no CI workflow. |
| sample-ambient-agent | None. Model: Sonnet 4.5 | `agent/tests/test_ask_human_stops_graph.py`, `test_guardrail_and_untrusted_tagging.py`, `test_guardrail_blocks_payload_integration.py`, `backend/tests/contracts`. These are safety and contract tests, not quality evals. CI does security and compliance checks only. |
| sample-ambient-agents-on-agentcore | None. Model: Sonnet 4.5 | Optional LangSmith tracing in `ambient_agent.py` (lines 10 to 14). `agentcore/agentcore.json` has an empty `"evaluators": []` slot for AgentCore Evaluations. There's one CDK test. |
| sample-human-in-the-loop-patterns | None. No model set; uses the Strands default | No tests. |
| sample-social-intelligence-agents | None. Model: Sonnet 4.6 | The most complete. `eval/golden_set.json` has 13 prompts, each with `expected_type` and `min_score`. `scripts/eval_quality.py` has `--offline` (checks structure and grounding with no AWS) and `--live` (runs each prompt on AgentCore, then a Sonnet 4.6 LLM judge scores relevance and grounding 1 to 10, with the judge model set by `JUDGE_MODEL_ID`). `scripts/benchmark.py` pulls token counts from spans through `bedrock_agentcore.evaluation` and works out cost from rates you supply. It ignores cache tokens. `tests/test_eval_quality.py`. `.github/workflows/ci.yml` runs unit tests and CDK synth checks, but not the eval. |

## 4. Recommendation for the pattern library

Caching:
- Add a `primitives/model/` building block that every pattern uses to create its model. It should set Strands `CacheConfig(strategy="auto")` by default, sort tools by name, and keep dates and IDs out of the system prompt (pass them in the user turn).
- Add a `model:` section to `pattern.yaml` with `id`, `cache: auto|off`, `cache_ttl_static: 5m|1h`, `cache_ttl_messages: 5m|off`, and `tenant_isolated_cache: true|false`. Background and approval patterns should default to `1h` for tools and system. Chat should default to `5m`.
- Make `primitives/tracing` record `cacheReadInputTokens` and `cacheWriteInputTokens` on every call, plus a cache hit ratio and cost that includes the write premium. Fix the FAST context check so it adds write tokens.
- Add one CI test per pattern that runs two identical calls (or a recorded fixture) and checks the second call has reads above zero. This catches a timestamp or reordered tool slipping into the prefix. Also warn when the static prefix is below the model's minimum, for example under 4,096 tokens on Haiku 4.5.

Testing:
- Build `primitives/eval/` on two tools. The first is the Strands Evals SDK for fast local and PR checks (OutputEvaluator, TrajectoryEvaluator, deterministic checks). The second is AgentCore Evaluations for the managed judge, ground truth trajectories, and online monitoring. Use social intelligence's offline and live split as the model.
- Give every pattern an `eval/golden_set.json` in the AgentCore dataset shape: `scenario_id`, `turns[].input`, `expected_response`, `expected_trajectory`, `assertions`, `min_score`.
- Add an `eval:` section to `pattern.yaml` listing evaluators (default GoalSuccessRate, Correctness, ToolSelectionAccuracy, ToolParameterAccuracy, plus TrajectoryInOrderMatch for tool agents and Harmfulness, Refusal and Stereotyping for user-facing ones), the threshold (0.8), runs per case, and the online sampling rate.
- CI should run in three tiers. On every PR, run unit tests, CDK synth, the offline golden set check, the cache-hit check, and evaluation of stored trace fixtures (no deploy). On merge or nightly, deploy to dev, run the dataset runner with live AgentCore Evaluate, block on threshold, and tear down. In production, use online evaluation at about 10% sampling with CloudWatch alarms on score drops.
- Use Lambda code evaluators for exact business checks. Leave out fmeval and intelligent prompt routing for now.

# Attribution: bojieli/ai-agent-book

Decision frameworks in the playbooks under `docs/` come from the companion skills for the book *AI Agent*.

| | |
| --- | --- |
| Repository | [bojieli/ai-agent-book](https://github.com/bojieli/ai-agent-book) |
| Skills | [skills/](https://github.com/bojieli/ai-agent-book/tree/main/skills) (22 skills) |
| Author | Bojie Li |
| License | [Apache License 2.0](https://github.com/bojieli/ai-agent-book/blob/main/LICENSE), Copyright 2025 Bojie Li |

This repository does not vendor those `SKILL.md` files. The pages here are original AgentCore writeups. They restate selected decision rules in the language of Runtime, Gateway, Memory, Guardrails, and `RuntimeHarness`, and they link back for chapter text and experiment code. Long quotations were avoided after checking that license.

pstack remains the general method. These pages do not restate its playbooks. The overlap map is [skills/pstack-vs-agentcore.md](../skills/pstack-vs-agentcore.md).

## Idea to source

| This repo | Source skill | Book chapter (upstream README) |
| --- | --- | --- |
| [evals/dataset-design.md](../evals/dataset-design.md) | `eval-dataset-design` | ch7, `book/chapter7.md` |
| Eval pack already in [evals/README.md](../evals/README.md) (model plus harness, deterministic checks, traces) | `agent-evaluation` | ch7 |
| [tools/design.md](../tools/design.md) | `tool-design` | ch4, `book/chapter4.md` |
| [tools/discovery.md](../tools/discovery.md) | `tool-discovery` | ch4 |
| [tools/mcp-and-skills.md](../tools/mcp-and-skills.md) | `mcp-skill-hub` | ch4 |
| [runtime/error-recovery.md](../runtime/error-recovery.md) | `error-recovery` | ch5, `book/chapter5.md` |
| [runtime/loop-and-verifiers.md](../runtime/loop-and-verifiers.md) | `loop-engineering` | ch10, `book/chapter10.md` |
| [runtime/context-budget.md](../runtime/context-budget.md) | `context-compression`, `agent-state-bar`, `kv-cache-design` | ch2, `book/chapter2.md` |
| [prompts/context-engineering.md](../prompts/context-engineering.md) | `context-engineering` | ch2 |
| [orchestration/multi-agent.md](../orchestration/multi-agent.md) | `multi-agent-design` | ch10 |
| [ops/experience-loop.md](../ops/experience-loop.md) | `agent-evolution` | ch9, `book/chapter9.md` |
| [memory/overview.md](../memory/overview.md) (stub only) | `memory-system` | ch3, `book/chapter3.md` |

Upstream experiment trees (`chapter2/`, `chapter4/`, `chapter7/`, and the rest) stay in that repository. Do not copy them into `experiments/` as if they were ours.

## Explicit skip

These source skills are not adopted as docs pages or as skills in this repo.

| Source skill | Why it stays out |
| --- | --- |
| `computer-use` | Screenshot-and-act GUI agents. Business-process agents here call Runtime and Gateway, not a mouse and keyboard. |
| `post-training-strategy` | Mid-training, SFT, RL, and LoRA. This repo calls hosted models through Runtime. It does not train them. |
| `reward-design` | RL reward functions. Keep deterministic eval verifiers and policy checks. |
| `bad-case-to-dpo` | Production failures become preference pairs. Our path is a failing eval, then a fix. See [ops/experience-loop.md](../ops/experience-loop.md). |
| `coding-agent-harness` | IDE harness product. Acceptance, boundaries, feedback, and rollback already live in DESIGN §1 and §4. No second skill. |

Also skipped: wholesale copies of any upstream `SKILL.md`; Mem0 or Memobase how-tos (concepts only, on the future memory shelf); self-modifying harness loops and browser-workflow compilers from `agent-evolution`.

## Deferred

Not a skip forever. Write them when a later lease needs them.

| Source skill | Wait for |
| --- | --- |
| `async-event-agent` | Webhook, timer, and interrupt work on a Runtime template |
| `rag-pipeline`, `knowledge-org` | A retrieval or knowledge-base shelf |
| Full sleep-time evolution in `agent-evolution` | Boringly green Runtime, tools, memory, and eval templates (DESIGN §5) |

`kv-cache-design` is folded into [runtime/context-budget.md](../runtime/context-budget.md) as a short prefix rule. It does not have its own page.

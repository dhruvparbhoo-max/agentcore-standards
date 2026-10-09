# agentcore-standards

This repo is a library of tested agent patterns for Amazon Bedrock AgentCore that you can copy and use. The patterns share the same building blocks, so our team can build and ship safe agents faster.

An **agent** is a program that uses an AI model to carry out a task. It can look things up, call tools and take actions. **AgentCore** is the AWS service that runs our agents and gives them memory, tools and sign-in.

## How it's organised

- **`primitives/`** holds the building blocks. Each one is written once, tested once and shared by every agent. Examples are tracing (a record of each step the agent took, how long it took and what it cost), evals (the agent's exam), approvals (asking a person before a risky action), memory and guardrails (safety checks on what goes in and out).
- **`patterns/`** holds the agents. Each pattern is a small, complete example you can copy and deploy on its own. It contains only the parts that make it different.
- **`primitives/gateway-tools/`** holds the tools agents can use, like "look up an invoice" or "send a Slack message". It contains one tool list that shows every tool, what it does and which agents use it. It also has a starter tool in `_template/` that you copy when you add a new one.
- **`primitives/agent/`** holds the agent's main loop, which decides the next step. It uses LangChain's `create_agent` by default. Setting `framework: strands` in `pattern.yaml` switches to Strands, Amazon's agent framework. Tools, prompts, memory, tracing and approvals sit outside the loop, so they work the same either way.
- **`primitives/knowledge/`** holds a searchable library of documents, built on a Bedrock Knowledge Base. An agent can look up the right passage and quote it rather than relying on what the model remembers.
- **`infra/constructs/`** holds the cloud setup for each building block. Patterns use it to deploy themselves.
- **`docs/`** holds the design notes and the catalogue for picking a pattern.

A planned front door (not built yet) will handle verified login, a kill switch, shared model access, cost budgets, and an audit trail.

Every pattern comes with the same kit:

- a README
- a `pattern.yaml` settings file that says what starts the agent, which tools and model it uses, what it remembers and which actions need a person's approval
- prompts kept in their own files
- tracing turned on
- tests
- an exam made of real tasks
- sample inputs so you can run it quickly
- safety checks
- limits on cost and time
- one command to deploy it and one to remove it

The aim is that automatic checks fail any agent that has no tracing, no exam, no limits on its tools, or no approval step for risky actions. `agentcore-kit check-kit` is that check.

## Before you start

You need Python 3.12, [uv](https://docs.astral.sh/uv/), and Docker, or [Finch](https://runfinch.com) on a Mac. `docker ps` (or `finch ps` with `DOCKER=finch`) must succeed before you run a local stack.

```bash
uv sync --all-packages
make local
```

`make local` starts the sample agent, a Gateway tool, DynamoDB Local and LocalStack, then posts the pattern's sample events. You do not need AWS for that.

## How to pick and run a pattern

1. Open `docs/catalog.md`. Find the problem you're trying to solve and see which pattern it points to.
2. Read that pattern's README and `docs/design.md` to see what it does, what it can't do and when another pattern would suit you better.
3. Run it on your laptop with the sample inputs in its `events/` folder. You don't need AWS for this.
4. Copy the pattern folder, change the prompts, tools and exam to fit your job, and deploy it with its one deploy command.

Patterns being built first are a company-policy question-and-answer agent (it answers questions from policy documents, quotes the section and source, and says so when it can't find the answer), a human approval agent (four ways to ask a person before acting) and an ambient agent (one that reacts to events on its own). Copy `patterns/_template/` to start a new one. Those three named patterns are still to come. `primitives/knowledge/` and `docs/catalog.md` are not in the repo yet. None of this has been tested on a live AWS account yet.

## How changes are tested

- **On every pull request**, quick checks run and need no AWS: tool tests, format checks, a kit check, and a check that examples do not paste in copies of the shared building blocks.
- **On merge, every night and before each release** there is no deploy. No pattern is sent to an AWS account, and nothing is removed afterwards because nothing was started.

## How to add a tool

1. Copy `primitives/gateway-tools/_template/` to a new folder named after your tool.
2. Fill in the parts that come with it: what the tool does and what goes in and out of it, the code that does the work, a rule saying which agents may use it, a test of the tool itself, a test that checks what goes in and comes out, and a short README.
3. Add the tool to the tool list.
4. List the tool in the `pattern.yaml` of each agent that needs it. The agent then picks it up from the tool list, so nobody copies code around.

## Come back to later

These are known gaps. None of them is being built yet. Research and sources are in [docs/research/](docs/research/).

**Pick these up first**

1. **Checkpoint and resume.** The agent saves its progress after each step, so it can pick up where it stopped when AgentCore ends a session (after 15 idle minutes or 8 hours in total).

**Also parked**

2. **Prompt caching.** The model can reuse the part of a prompt that stays the same, which makes each request cheaper and faster. Tools always go in the same order, and anything that changes, like dates and IDs, goes at the end. Tracing will show the real cost, and an automatic check will confirm caching works.
3. **Model testing.** Strands Evals gives a quick check on every change. AgentCore Evaluations grades the deployed agents every night and keeps watching them once they're live. Each `pattern.yaml` sets which graders to use and the pass mark.

**After that, in this order**

4. **Context window management.** We'll set rules for clearing out or summarising old material, so the agent's working memory doesn't fill up and get worse.
5. **Check the output before acting.** Anything the model produces gets checked against the expected format and our business rules before the agent acts on it.
6. **Check facts before saving them to memory.** Before a fact goes into long-term memory, it gets checked and labelled with where it came from, so one wrong or planted fact can't mislead the agent later.
7. **Release everything together.** An agent's prompts, model, tools and rules go out together as one numbered version, so we can roll back if something breaks.
8. **Dev, staging and prod accounts.** Each agent is tried in separate test accounts and only reaches the live account after it passes its exam and a person signs off.
9. **Targets and alerts.** Each pattern has targets for success rate, speed and cost, and we get an alert when it misses them.
10. **Progress updates.** Long tasks show what the agent is doing right now, so people don't assume it's stuck and start it again.
11. **Safe tools.** We only use approved and pinned tool versions, and someone reviews any change to a tool's description.
12. **Versioned tools.** Each tool has a version number, so changing one doesn't quietly break the agents that use it.
13. **Containing failures between agents.** When agents work as a team, one failing agent gets cut off before it can drag the others down.
14. **Clear approval screens.** Approval requests show plainly what will happen and how risky it is, so people read them rather than clicking yes out of habit.
15. **Attack tests and threat model.** Each pattern faces a set of known attack prompts on every change, and gets a written list of how it could be attacked.
16. **Owner and risk level.** Every agent has a named owner, a note of how much it can do without a person, and a risk level.
17. **Learn from feedback.** Thumbs down and rejected approvals become new exam questions.
18. **Several teams sharing.** If other teams or customers use this, each one's data and usage stays separate from the others.
19. **Agent list and model retirement.** We keep one list of every live agent and get a warning before a model it uses is switched off.
20. **Smaller items.** Keep knowledge sources up to date. Run any code the agent writes in a sealed-off box. Have backups and a recovery plan. Make screens usable for everyone (the WCAG 2.2 accessibility standard). Add a "do you even need an agent?" question to the catalogue.
21. **Teams and Slack.** People can talk to agents and approve their actions from inside Microsoft Teams or Slack, through one shared connector with a Teams version and a Slack version.
22. **Reliable scheduled and background agents** (not built yet). Make scheduled and background agents reliable: track where each source stopped, flag failed reads, re-check items before posting, never post twice, and cap spend per run. [Building effective agent automations](https://claude.dev/blog/building-effective-agent-automations/)

## For developers

Setup, test commands, the directory tree and team rules are in [docs/developer-guide.md](docs/developer-guide.md) and [AGENTS.md](AGENTS.md). Shared design choices are in [docs/design/library.md](docs/design/library.md).

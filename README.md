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

The aim is that automatic checks fail any agent that has no tracing, no exam, no limits on its tools, or no approval step for risky actions. That check is not in the repo yet.

## How to pick and run a pattern

1. Open `docs/catalog.md`. Find the problem you're trying to solve and see which pattern it points to.
2. Read that pattern's README and `docs/design.md` to see what it does, what it can't do and when another pattern would suit you better.
3. Run it on your laptop with the sample inputs in its `events/` folder. You don't need AWS for this.
4. Copy the pattern folder, change the prompts, tools and exam to fit your job, and deploy it with its one deploy command.

Patterns being built first are a company-policy question-and-answer agent (it answers questions from policy documents, quotes the section and source, and says so when it can't find the answer), a human approval agent (four ways to ask a person before acting) and an ambient agent (one that reacts to events on its own). For now, the shared building blocks are in place and the patterns are still to come. These paths named above are not in the repo yet: `patterns/`, `primitives/gateway-tools/` (including `_template/`), `primitives/agent/`, `primitives/knowledge/`, `infra/constructs/`, `docs/catalog.md`, and `docs/design.md`. Tools that are here today live in `primitives/tools/`. The LangChain loop that is here today lives in `primitives/langchain/`. There is no `pattern.yaml` and no switch to Strands. None of this has been tested on a live AWS account yet.

## How changes are tested

- **On every pull request**, quick checks run and need no AWS: tool tests, format checks, and a check that examples do not paste in copies of the shared building blocks. They do not check that cloud setup builds, because that folder is not in the repo yet.
- **On merge, every night and before each release** there is no deploy. No pattern is sent to an AWS account, and nothing is removed afterwards because nothing was started.

## How to add a tool

1. Copy `primitives/gateway-tools/_template/` to a new folder named after your tool. That folder is not in the repo yet.
2. Fill in the parts that come with it: what the tool does and what goes in and out of it, the code that does the work, a rule saying which agents may use it, a test of the tool itself, a test that checks what goes in and comes out, and a short README.
3. Add the tool to the tool list.
4. List the tool in the `pattern.yaml` of each agent that needs it. The agent then picks it up from the tool list, so nobody copies code around.

## Come back to later

These are known gaps. None of them is being built yet. Research and sources are in [docs/research/](docs/research/).

**Pick these up first**

1. **Agent identity.** When an agent acts for a person, it uses a short-lived pass tied to that person, so it can never do more than they could.
2. **Checkpoint and resume.** The agent saves its progress after each step, so it can pick up where it stopped when AgentCore ends a session (after 15 idle minutes or 8 hours in total).
3. **Shared model access.** Every agent calls the AI model the same way. If the model is busy it waits and tries again, it can switch to a backup model, it keeps data in UK or EU regions, and it has usage limits.
4. **Kill switch and runbooks.** We can stop one agent, one tool or every agent within minutes, and short written guides say what to do when an agent misbehaves.
5. **Privacy and audit trail.** Personal details get hidden, we decide where data lives and how long we keep it, and a permanent record shows who asked for what, what the agent did and who approved it.

**Also parked**

6. **Prompt caching.** The model can reuse the part of a prompt that stays the same, which makes each request cheaper and faster. Tools always go in the same order, and anything that changes, like dates and IDs, goes at the end. Tracing will show the real cost, and an automatic check will confirm caching works.
7. **Model testing.** Strands Evals gives a quick check on every change. AgentCore Evaluations grades the deployed agents every night and keeps watching them once they're live. Each `pattern.yaml` sets which graders to use and the pass mark.

**After that, in this order**

8. **Context window management.** We'll set rules for clearing out or summarising old material, so the agent's working memory doesn't fill up and get worse.
9. **Check the output before acting.** Anything the model produces gets checked against the expected format and our business rules before the agent acts on it.
10. **Check facts before saving them to memory.** Before a fact goes into long-term memory, it gets checked and labelled with where it came from, so one wrong or planted fact can't mislead the agent later.
11. **Release everything together.** An agent's prompts, model, tools and rules go out together as one numbered version, so we can roll back if something breaks.
12. **Dev, staging and prod accounts.** Each agent is tried in separate test accounts and only reaches the live account after it passes its exam and a person signs off.
13. **Targets and alerts.** Each pattern has targets for success rate, speed and cost, and we get an alert when it misses them.
14. **Cost tags and budgets.** Spending is tracked per agent, and a budget sends a warning first and then stops it.
15. **Progress updates.** Long tasks show what the agent is doing right now, so people don't assume it's stuck and start it again.
16. **Safe tools.** We only use approved and pinned tool versions, and someone reviews any change to a tool's description.
17. **Versioned tools.** Each tool has a version number, so changing one doesn't quietly break the agents that use it.
18. **Containing failures between agents.** When agents work as a team, one failing agent gets cut off before it can drag the others down.
19. **Clear approval screens.** Approval requests show plainly what will happen and how risky it is, so people read them rather than clicking yes out of habit.
20. **Attack tests and threat model.** Each pattern faces a set of known attack prompts on every change, and gets a written list of how it could be attacked.
21. **Owner and risk level.** Every agent has a named owner, a note of how much it can do without a person, and a risk level.
22. **Learn from feedback.** Thumbs down and rejected approvals become new exam questions.
23. **Several teams sharing.** If other teams or customers use this, each one's data and usage stays separate from the others.
24. **Agent list and model retirement.** We keep one list of every live agent and get a warning before a model it uses is switched off.
25. **Smaller items.** Keep knowledge sources up to date. Run any code the agent writes in a sealed-off box. Have backups and a recovery plan. Make screens usable for everyone (the WCAG 2.2 accessibility standard). Add a "do you even need an agent?" question to the catalogue.
26. **Teams and Slack.** People can talk to agents and approve their actions from inside Microsoft Teams or Slack, through one shared connector with a Teams version and a Slack version.

## For developers

Setup, test commands and team rules are in [docs/developer-guide.md](docs/developer-guide.md) and [AGENTS.md](AGENTS.md).

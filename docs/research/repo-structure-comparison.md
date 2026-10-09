# AWS agent reference repos: structure comparison

Checked on 8 Oct 2026 (UK time). Each repo was shallow-cloned (latest commit only) into `/workspace/aws-refarch/` and its file tree listed. Everything below comes from those trees. Where I didn't see a folder, I say so rather than guessing.

Terms used:
- IaC (infrastructure as code): files that create the cloud resources.
- CDK: AWS Cloud Development Kit, which writes infrastructure in TypeScript or Python.
- CloudFormation: AWS's own YAML or JSON template format.
- Terraform: a non-AWS infrastructure tool.
- MCP: Model Context Protocol, a standard way to expose tools to an agent.
- Evals: automatic scoring of agent quality, as opposed to tests that check code.
- CI: automatic checks that run on every push.

## Summary table

| Repo (latest commit) | Language and agent framework | IaC tool | Top-level layout |
|---|---|---|---|
| sample-ambient-agent (6 Oct 2026) | Python agent, LangChain + LangGraph. TypeScript React front end | CDK Python in `backend/`, plus IAM policy JSON in `agent/policies/` | `agent/` `backend/` `frontend/` `.devsecops/` `.github/` |
| sample-ambient-agents-on-agentcore, AgentWatch (13 Apr 2026) | Python, LangChain + LangGraph | Two kinds: CDK TypeScript made by the AgentCore CLI (`agentcore/cdk/`) and raw CloudFormation (`deployment/cloudformation/`) | Flat. `ambient_agent.py` sits at the root, next to `agentcore/` `deployment/` `idp_setup/` `lambda/` `prompt_templates/` `tools/` |
| sample-human-in-the-loop-patterns (17 Mar 2026) | Python, Strands, FastMCP for the MCP server | Raw CloudFormation (`infra/cloudformation.yaml`). Agents are deployed with the AgentCore CLI from shell scripts | `infra/` plus one folder per pattern: `method1_hook/` `method2_tool_context/` `method3_remote_sfn/` `method4_mcp_elicitation/` |
| sample-social-intelligence-agents (22 Aug 2026) | Python (managed with uv), Strands, Pydantic, Streamlit demo | CDK Python in `infra/` | `src/social_intelligence/` `infra/` `tests/` `eval/` `scripts/` `demo/` `config/` `architecture/` `.github/` |
| fullstack-solution-template-for-agentcore, FAST (8 Oct 2026) | Python agents in six patterns (Strands, LangGraph, Claude Agent SDK, AG-UI variants). TypeScript React front end | CDK TypeScript (`infra-cdk/`) and Terraform (`infra-terraform/`), both kept up to date side by side | `patterns/` `gateway/` `tools/` `infra-cdk/` `infra-terraform/` `frontend/` `tests/` `test-scripts/` `scripts/` `docs/` `vibe-context/` `docker/` `.github/` `.mkdocs/` |
| guidance-for-multi-agent-orchestration-using-bedrock-agentcore-on-aws (13 Feb 2026) | Python, Strands (with the A2A extra, A2A being the agent-to-agent protocol) + bedrock-agentcore. TypeScript React front end | CDK TypeScript in `infrastructure/` | `agents/` `infrastructure/` `frontend/` `lambda/` `tests/` `scripts/` `knowledge-base-data/` |

Searched once, not found:
- **Serverless Land sample for the Step Functions validation post (airline rebooking).** No repo turned up. Two related but different repos did:
  - `aws-samples/sample-durable-multi-agent-step-functions-agentcore`, a product-discovery workflow
  - `aws-samples/serverless-patterns/sfn-parallel-bedrock-agentcore-multi-agent-cdk`, a parallel research fan-out

  Neither is the airline workflow, so I didn't inspect them.
- **Multi-account Gateway/MCP post repo.** Not found. The nearest hits were other Okta and Gateway samples (`aws-samples/sample-bedrock-agentcore-gateway-user-federation`, `aws-samples/sample-obo-flow-poc`). Neither is the four-account sample from the post.

## Per-repo detail

### 1. aws-samples/sample-ambient-agent (the original ambient agents post)
- **Agent code:** `agent/agent.py` is the entry point. The logic is in `agent/core/`: `agent_core.py`, `execution_control.py` and `tool_factory.py`. Has a `Dockerfile`.
- **IaC:** CDK Python under `backend/`:
  - `app.py` and `cdk.json`
  - `infrastructure/multi_agent_stack.py`, `infrastructure_stack.py` and `config.py`

  IAM policy documents live in `agent/policies/*.json` and are attached by `agent/attach_agent_policies.sh`.
- **Tools / MCP:** `agent/tools/` holds `calculator.py`, `human_input.py` (the ask_human tool) and `s3_reader.py`. There's no MCP server.
- **Front end:** React + Vite in `frontend/`, with pages for jobs, signals, agents, chat, workflows, dashboard and settings.
- **Event and trigger handlers:** Lambdas in `backend/functions/multi_agent/`:
  - `signal_processor.py` and `scheduler.py`
  - `job_management.py`, `chat_execution.py`, `chat_management.py`, `conversation_management.py`, `agent_management.py` and `signal_management.py`
  - `authz.py` and `metrics.py`

  There's also a custom resource in `backend/functions/custom_resources/`.
- **Tests:**
  - `agent/tests/` has 3 tests: ask_human stops the graph, guardrail and untrusted-input tagging, and a guardrail integration test.
  - `backend/tests/contracts/` has 2 tests: the agent response format and session ID handling.
- **Evals:** none.
- **Config and prompts:** `agent/config.example.yaml` (the system prompt is inside it), `agent/.env.example` and `backend/config.example.yml`.
- **Deploy scripts:** `agent/deploy_agent.sh` and `agent/attach_agent_policies.sh`. The backend is deployed with `cdk deploy`.
- **Docs:** `README.md`, `agent/README.md`, `THREAT_MODEL.md`, `.github/workflows/README.md` and `frontend/src/docs/TANSTACK_QUERY_GUIDE.md`.
- **CI:** `.github/workflows/security-compliance.yml` runs a security scan (ASH), a secrets scan (Ferret) and a licence check. It doesn't run the tests.
- **Other:** `.pre-commit-config.yaml`, `.pylintrc`, `.devsecops/`.

### 2. aws-samples/sample-ambient-agents-on-agentcore (AgentWatch)
- **Agent code:** `ambient_agent.py` at the repo root, alongside `constants.py`, `utils.py` and `get_agent_url.py`.
- **IaC:** two separate sets.
  - `agentcore/` is an AgentCore CLI project (`agentcore.json`, `aws-targets.json`) containing a CDK TypeScript app in `agentcore/cdk/` (`bin/cdk.ts`, `lib/cdk-stack.ts`).
  - `deployment/cloudformation/cloudformation.yaml` is raw CloudFormation. It creates API Gateway, Cognito, an EventBridge rule, a Lambda function, a Secrets Manager secret and an IAM role.
- **Tools / MCP:** `tools/cloudwatch_tools.py` and `tools/aws_helpers.py`. There's no MCP server.
- **Front end:** none. Slack is the interface.
- **Event and trigger handlers:** `lambda/scheduled_monitor.py`. The CloudFormation template also defines the EventBridge rule (the 15-minute timer) and the API Gateway route for the Slack slash command.
- **Tests:** only `agentcore/cdk/test/cdk.test.ts`, a CDK template test. There are no agent tests.
- **Evals:** none.
- **Config and prompts:** `config.yaml`, `constants.py`, `.env.example` and `prompt_templates/ambient_agent_system_prompt.txt`.
- **Deploy scripts:** in `deployment/`:
  - `deploy.sh`, `deploy_agentcore.sh` and `agentcore_cli.sh`
  - `sync_agentcore_config.py`
  - `cloudformation/deploy-stack.sh`

  There's also `idp_setup/setup_cognito.py`.
- **Docs:** `README.md`, `agentcore/cdk/README.md` and `deployment/cloudformation/README.md`.
- **CI:** none.
- **Oddity:** log files are committed to git: `deployment/logs/combined.log`, `error.log` and `interactions.log`.

### 3. aws-samples/sample-human-in-the-loop-patterns
- **Agent code:** each pattern folder has its own `agent.py`:
  - `method1_hook/`
  - `method2_tool_context/`
  - `method3_remote_sfn/`
  - `method4_mcp_elicitation/`, which also has `local_agent_main.py` and `agent_deploy.sh`
- **IaC:**
  - `infra/cloudformation.yaml` is raw CloudFormation. It creates a Cognito user pool and client, IAM roles and a policy, one Lambda function, an SNS topic and a Step Functions state machine. The Lambda code is written inline in the template.
  - `infra/deploy.sh` deploys that template.
  - Each pattern's `deploy.sh` runs `agentcore configure` and `agentcore launch`.
- **Tools / MCP:**
  - Tools are defined inside each `agent.py`.
  - The MCP server is `method4_mcp_elicitation/server.py` (FastMCP).
  - `method3_remote_sfn/approve.py` is the approval helper.
- **Front end:** none.
- **Event and trigger handlers:** only the Step Functions machine and the inline Lambda in the CloudFormation template.
- **Tests:** each `test.py` is an interactive client that calls the deployed agent. These aren't automated tests.
- **Evals:** none.
- **Config and prompts:** `pyproject.toml` and a `requirements.txt` per pattern. I saw no separate prompt files.
- **Deploy scripts:** one `deploy.sh` per folder.
- **Docs:** `README.md` only.
- **CI:** none.

### 4. aws-samples/sample-social-intelligence-agents (Thrad.ai)
- **Agent code:** `src/social_intelligence/`:
  - `agents/`: four agents (trend research, search specialist, analysis, email generation)
  - `orchestration/`: `graph_runner.py`, `swarm_runner.py`, `qualification_gate.py`, `model_retry.py` and `tool_budget.py`
  - `schemas/`: Pydantic models, `openapi.yaml` and `tool_schema.json`
  - `config.py`

  The AgentCore entry point is `entrypoint.py` at the root.
- **IaC:** CDK Python in `infra/`: `app.py`, `stacks/social_intelligence_stack.py` and `gateway_stack.py`. `infra/lambda/handler.py` is the Lambda that serves tools behind AgentCore Gateway.
- **Tools / MCP:** `src/social_intelligence/tools/` holds 14 tool modules plus `registry.py` (Hacker News, Reddit, GitHub, YouTube, DynamoDB, grounding gate and others). Some are exposed through the Gateway Lambda. Others are imported directly by the agent, per the `entrypoint.py` docstring.
- **Front end:** `demo/`, a Streamlit app.
- **Event and trigger handlers:** none event-driven. The only Lambda is the Gateway tool target.
- **Tests:** `tests/` has 13 unit test files plus `tests/integration/test_runtime.py`.
- **Evals:**
  - `eval/golden_set.json` is the test prompt set.
  - `scripts/eval_quality.py` has an offline mode, which checks the set and runs the grounding gate. It also has a live mode, which runs prompts on AgentCore and scores the drafts with an LLM judge.
  - `scripts/benchmark.py` compares Swarm against Graph.
- **Config and prompts:** `config/icp_profile.json`, `src/social_intelligence/config.py` and `.env.example`. System prompts live inside the agent modules. There's no separate prompts folder.
- **Deploy scripts:** `cdk deploy`, plus `scripts/check_synth.py` and `scripts/test_invoke.py`.
- **Docs:** `README.md`, `SECURITY.md`, and `architecture/README.md` with three draw.io diagrams.
- **CI:** `.github/workflows/ci.yml` runs lint, a format check, unit tests and `cdk synth`. Dependabot is turned on.

### 5. awslabs/fullstack-solution-template-for-agentcore (FAST)
- **Agent code:** `patterns/<pattern>/`. Each pattern folder has a `Dockerfile`, an agent file, `requirements.txt` and usually a `tools/` folder. The six patterns are:
  - `strands-single-agent`
  - `langgraph-single-agent`
  - `agui-strands-agent`
  - `agui-langgraph-agent`
  - `claude-agent-sdk-single-agent`
  - `claude-agent-sdk-multi-agent`

  Shared helpers are in `patterns/utils/` (`auth.py`, `ssm.py`). You pick the pattern in `infra-cdk/config.yaml`.
- **IaC:** two complete versions.
  - `infra-cdk/` is CDK TypeScript: `bin/`, `lib/` constructs for backend, Cognito and Amplify, `config.yaml`, `test/`, and `lambdas/`. The Python Lambdas cover feedback, Cedar policy, the OAuth2 provider, the pretoken step and the zip packager.
  - `infra-terraform/` has modules for backend (runtime, memory, gateway, auth, ssm), Cognito and Amplify hosting.
- **Tools / MCP:**
  - `gateway/tools/sample_tool/` (a Lambda plus `tool_spec.json`)
  - `gateway/policies/policy.cedar`
  - `tools/code_interpreter/`
  - per-pattern `tools/gateway.py`, `code_interpreter.py` and `mcp_registry.py`
  - the Claude patterns include a small MCP server in `code_int_mcp/`
- **Front end:** React + Vite in `frontend/`, with Vitest tests in `frontend/src/test/` (9 files).
- **Event and trigger handlers:** none. The Lambdas are support functions only (feedback API, auth, packaging).
- **Tests:**
  - `tests/unit/test_mcp_registry.py`
  - `tests/integration/`, which holds only `__init__.py`
  - front end tests
  - `infra-cdk/test/fast-cdk.test.ts`
  - `test-scripts/`, which are live smoke checks for the agent, gateway, memory and feedback API
- **Evals:** guidance only, in `docs/AGENTCORE_EVALUATIONS_GUIDE.md`. There's no eval code or dataset.
- **Config and prompts:** `infra-cdk/config.yaml`, `infra-terraform/terraform.tfvars.example`, `ruff.toml` and `pyproject.toml`. Prompts sit inside the agent files.
- **Deploy scripts:**
  - `scripts/deploy-frontend.py` and `scripts/deploy-with-codebuild.py`
  - `infra-terraform/scripts/` (build and push image, deploy front end, test agent)
  - The `Makefile` has lint targets only.
- **Docs:**
  - `docs/` has 25 guides covering gateway, memory, identity, Cedar, observability, evaluations, Terraform, streaming and more.
  - There's an MkDocs site setup and a draw.io architecture diagram.
  - `vibe-context/` holds rules for AI coding assistants: `AGENTS.md` and the coding conventions.
- **CI:**
  - GitHub workflows run security scans (ASH), JS lint, Python lint with ruff, Dependabot, a labeler and repo stats.
  - `.gitlab-ci.yml` runs `make lint-cicd`, a security scan and docs pages.
  - Neither runs the Python tests, as far as the workflow files show.

### 6. aws-solutions-library-samples/guidance-for-multi-agent-orchestration-using-bedrock-agentcore-on-aws
- **Agent code:** `agents/<agent-name>/`, one folder each for the supervisor, order management, personalization, product recommendation and troubleshooting agents.
  - Each specialist has `Dockerfile`, `agent.py`, `system_prompt.py` and `infrastructure/gateway_provider.py`. For product recommendation, `gateway_provider.py` sits under `gateway/infrastructure/` instead.
  - The supervisor uses a different layout: `src/customer_support_assistant/` with `agents/supervisor.py`, `tools/` (clients that call the sub-agents) and `utils/`.
  - There are no `requirements.txt` files. Dependencies are installed inside each Dockerfile.
- **IaC:** CDK TypeScript in `infrastructure/`. There's one stack per agent, plus stacks for the knowledge base, the front end and the main system. It also has `deploy-complete-system.sh` and `cleanup.sh`.
- **Tools / MCP:** `agents/<name>/gateway/lambdas/*/lambda_function.py` with matching `gateway/schemas/*.json`. Each specialist owns its Gateway tools.
- **Front end:** React + Vite + Tailwind in `frontend/`.
- **Event and trigger handlers:** none. `lambda/agent-deployer/` and `lambda/memory-manager/` are CloudFormation custom resources that manage AgentCore runtimes and memory.
- **Tests:**
  - `tests/unit/` has 2 files.
  - `tests/integration/` runs in stages against a deployed system: `00_setup`, `01_infrastructure`, `02_sub_agents` and `03_supervisor`.
- **Evals:** none.
- **Config and prompts:** `system_prompt.py` in each agent, plus `frontend/.env.example`.
- **Data:** `knowledge-base-data/` (sample browsing history and FAQs).
- **Scripts:** in `scripts/`:
  - `fix_all_runtime_auth.py`
  - `run_supervisor_tests.py`
  - `setup_test_users.py`
  - `show_agent_logs.py`
- **Docs:** `README.md`, the product recommendation agent's README and `tests/integration/README.md`.
- **CI:** none.

## Assessment: is there a shared structure?

Partly. Four of the six repos share a rough three-part shape:
1. a folder of agent code that builds a container (a Dockerfile plus Python)
2. a folder of IaC
3. a React + Vite front end

Those four are sample-ambient-agent, FAST, the multi-agent guidance repo and, minus the React part, social-intelligence. Tools sit next to the agent, or in a Gateway folder when they're served as Lambdas behind AgentCore Gateway.

Beyond that, the names and choices differ:
- **The infrastructure folder has a different name almost every time:** `backend/`, `infra/`, `infra-cdk/` + `infra-terraform/`, `infrastructure/`, `agentcore/cdk/` + `deployment/cloudformation/`.
- **The IaC tool varies:**
  - CDK Python: ambient agent, social intelligence
  - CDK TypeScript: FAST, guidance, AgentWatch
  - raw CloudFormation: HITL, AgentWatch
  - Terraform: FAST only
- **The agent folder varies:** `agent/`, `patterns/<name>/`, `agents/<name>/`, `src/<package>/agents/`, `methodN/`, or a single file at the root (AgentWatch).
- **Gateway tools sit in different places:** a top-level `gateway/` (FAST), per-agent `agents/<name>/gateway/` (guidance), or `infra/lambda/` (social intelligence).
- **Only sample-ambient-agent has a real event-driven backend**, meaning a signal processor, a scheduler and a job queue. AgentWatch has one scheduled Lambda. The others are request-driven (chat or a direct call).
- **Prompts live in three different ways:** a YAML config (ambient), `prompt_templates/*.txt` (AgentWatch), `system_prompt.py` per agent (guidance), or inline in agent code (FAST, social intelligence, HITL).

How each repo departs from the common shape:
- **sample-ambient-agent:** calls its IaC-plus-Lambdas folder `backend/`. It's the only one with a full event pipeline and a threat model document.
- **AgentWatch:** flat layout with the agent at the root. It has two overlapping IaC sets (CLI-made CDK and hand-written CloudFormation), no front end, and committed log files.
- **HITL patterns:** a teaching repo with one folder per pattern, raw CloudFormation and shell deploys. It has no tests or front end.
- **social-intelligence:** a proper Python package (`src/` layout) with a Streamlit demo instead of React. It's the only repo with evals.
- **FAST:** a template rather than a single solution. It ships pick-one agent patterns, two IaC options and heavy docs.
- **guidance:** one folder per agent, with each agent owning its own Gateway Lambdas and its own CDK stack. Its dependencies are buried in Dockerfiles.

**Cleanest template to copy:** FAST (`awslabs/fullstack-solution-template-for-agentcore`). Reasons:
- clear separation into `patterns/` (agent), `gateway/` (tools and Cedar policy), `infra-cdk/` or `infra-terraform/` (IaC) and `frontend/`
- one config file selects the agent pattern
- the widest docs, plus `vibe-context/` rules for AI coding assistants
- updated on 8 Oct 2026

For the testing and evals layout, copy social-intelligence's pieces instead: `tests/`, `eval/golden_set.json`, `scripts/eval_quality.py` and a CI job that runs unit tests and `cdk synth`. For the event-driven part, borrow `backend/functions/` (signal processor and scheduler) and the contract tests from sample-ambient-agent.

**What's commonly missing:**
- **Evals:** five of six have no eval code. FAST has a guide only, and only social intelligence has a golden set and an LLM-judge script.
- **CI that runs tests:** only social intelligence runs unit tests in CI. Ambient and FAST run security and lint checks only. AgentWatch, HITL and guidance have no CI at all.
- **Agent tests:** AgentWatch and HITL have none. FAST has one Python unit test file and an empty integration folder.
- **Event triggers:** only the original ambient repo and AgentWatch have them.
- **A single IaC choice:** AgentWatch and FAST each keep two IaC sets, which you'd need to keep in sync.

## Suggested common skeleton

Built from the parts that worked best across these repos:

```
repo/
  agents/<agent-name>/       # one folder per agent: Dockerfile, agent.py, requirements.txt, prompts/ (from FAST patterns/ and guidance agents/)
  tools/                     # in-process tools the agent imports directly
  gateway/
    tools/<tool>/            # Lambda + tool_spec.json, served behind AgentCore Gateway (FAST)
    policies/*.cedar         # Cedar rules for which tools are allowed (FAST)
  triggers/                  # event handlers: signal processor, scheduler, webhook Lambdas (sample-ambient-agent backend/functions/)
  infra/                     # one IaC tool only, e.g. CDK; stacks/ + config.yaml (FAST infra-cdk/, social infra/)
  frontend/                  # optional: jobs/approvals UI (sample-ambient-agent) or chat (FAST)
  tests/
    unit/
    contracts/               # agent response format, session ID handling (sample-ambient-agent)
    integration/             # run against a deployed stack (guidance's staged tests)
  eval/
    golden_set.json          # prompts plus expected outcomes (social intelligence)
  scripts/                   # deploy, invoke, eval_quality.py
  docs/                      # architecture diagram, threat model, per-feature guides
  .github/workflows/ci.yml   # lint, unit tests, IaC synth, security scan
  AGENTS.md                  # rules for AI coding assistants (FAST vibe-context/)
```

# Third-party sources

Production-readiness work copies from the reference repos named in the production readiness references (9 Oct 2026). This page lists every file in this repo that copies or adapts one of them, the exact source path, and the licence. The Apache-2.0 NOTICE text is in the root [`NOTICE`](../../NOTICE). Licence texts are in [`licenses/`](licenses/).

Each copied file also names its source in its own header, so the credit stays with the file if it moves.

## Licences checked

| Short name | Repository | Licence | Obligation |
| --- | --- | --- | --- |
| FAST | awslabs/fullstack-solution-template-for-agentcore | Apache-2.0 | Keep the NOTICE (reproduced in full) and the licence |
| ENTERPRISE | aws-samples/sample-agentcore-enterprise-platform | Apache-2.0 | Keep the NOTICE and the licence |
| CLI | aws/agentcore-cli | Apache-2.0 | Keep the NOTICE and the licence |
| SAMPLES | awslabs/amazon-bedrock-agentcore-samples | Apache-2.0 | Keep the NOTICE and the licence |
| LOOM | awslabs/loom | Apache-2.0 | Keep the NOTICE and the licence |
| SOCIAL | aws-samples/sample-social-intelligence-agents | MIT-0 | None; credited anyway |
| AGENT-PLATFORM | aws-samples/sample-agent-platform-with-agentcore | MIT-0 | None; credited anyway |
| EVAL-FIRST | aws-samples/sample-eval-first-building-enterprise-agents-with-agentcore | MIT-0 | None; credited anyway |
| TENANCY | aws-samples/sample-agentcore-and-multitenancy-blog | MIT-0 | None; credited anyway |
| CICD | aws-samples/sample-bedrock-agentcore-runtime-cicd | MIT-0 | None; credited anyway |
| CWL-DP | aws-samples/cloudwatch-logs-data-protection-policies-with-cdk | MIT-0 | None; credited anyway |
| DNS-FW | aws-samples/sample-route53-iac-with-cdk | MIT-0 | None; credited anyway |
| BOISE | Boise-State-Development/agentcore-public-stack | PolyForm Noncommercial 1.0.0 | **Not copied.** See below |

## Step 3: starter kits

| This repo | Source | What was taken |
| --- | --- | --- |
| `primitives/agent/src/agentcore_agent/secrets.py` | SOCIAL `src/social_intelligence/tools/_secrets.py`; FAST `patterns/utils/ssm.py` | `get_secret` with a 10 minute TTL cache that never logs or caches errors; `get_ssm_parameter` |
| `infra/constructs/src/agentcore_constructs/foundation.py` | SOCIAL `infra/stacks/social_intelligence_stack.py`; ENTERPRISE `stacks/runtime_stack.py`, `stacks/observability_stack.py`; CWL-DP `stacks/cloudwatch_policies.py` | KMS key with rotation, one secret per name with `grant_read` to one consumer, DESTROY only in dev; ECR scan on push and keep-last-10; log retention limited to 30/90/180/365; `DataProtectionPolicy` with managed identifiers and `logs:Unmask` policies |
| `config/environments/*.yaml`, `primitives/agent/src/agentcore_agent/environment.py`, `production.py` | ENTERPRISE `docs/PLATFORM_YAML.md`, `presets/production.yaml` | One file per environment; production retains state and refuses to continue when a required control is off; secrets referenced by name |
| `docker/base-agent/Dockerfile`, `patterns/_template/agent/Dockerfile` | FAST `patterns/strands-single-agent/Dockerfile` | Non-root user, `HEALTHCHECK` on `/ping`, `OTEL_PYTHON_LOG_CORRELATION` |
| `compose.yaml` | FAST `docker/docker-compose.yml` | Compose healthcheck on `/ping` |
| `.github/dependabot.yml` | SOCIAL `.github/dependabot.yml` | Grouped uv minor/patch, separate security group, grouped GitHub Actions |
| `.github/workflows/ci.yml` | SOCIAL `.github/workflows/ci.yml`; CICD `.github/workflows/deploy-agentcore.yml` | `uv lock --check` and `uv sync --locked`; SHA-pinned actions; arm64 buildx |
| `scripts/deploy.sh` | CICD `.github/workflows/deploy-agentcore.yml` | ECR `put-registry-scanning-configuration --scan-type ENHANCED` with `SCAN_ON_PUSH` |
| `primitives/agent/src/agentcore_agent/lifecycle.py` | SOCIAL `entrypoint.py` (lines 802 to 905); CLI `src/assets/python/http/bma/base/lifecycle/server.py` | `add_async_task` / `complete_async_task` around a background thread with `copy_context`; atomic `state.json.tmp` replace; SIGTERM and SIGINT handlers |
| `primitives/agent/src/agentcore_agent/logging.py` | SAMPLES `01-features/02-host-your-agent/01-runtime/04-coding-agents/05-autonomous-coding-agent-durable/shared/logging.py` | `StructuredJsonFormatter`, `CorrelatedLogger`, `update_correlation`; `user_id` added the same way as `session_id` |
| `primitives/agent/src/agentcore_agent/doctor.py` | ENTERPRISE `scripts/preflight.py` | Fixed read-only allow-list of AWS CLI calls, reporter shape |
| `primitives/agent/src/agentcore_agent/registry.py` | LOOM `backend/app/services/registry.py` | MCP descriptor shape for an Agent Registry record |
| `patterns/_template/policies/tools.cedar` | ENTERPRISE `control-library/cedar/gateway-default/10-permit-read-tools.cedar` | One permit per tool, scoped to the gateway resource |
| `patterns/_template/pattern.yaml` (`owner`, `alert_route`, `runbook_url`) | ENTERPRISE `use-cases/_template/manifest.yaml` | Validated `owner:` field; `alert_route` and `runbook_url` added next to it (the references note no repo has them) |

## Step 4: front door, network, alarms

| This repo | Source | What was taken |
| --- | --- | --- |
| `primitives/front-door/` (caller, sessions, governance, door, audit) | AGENT-PLATFORM (aws-samples/sample-agent-platform-with-agentcore) session binding, `governance_service.py`, audit rows, JWKS verifiers, the single invocation pipeline (MIT-0) | Verified caller, HMAC session ids, one lease per session, quotas, kill switches, fail-closed audit |
| `primitives/front-door/` (usage / retryable codes) | aws-samples/sample-eval-first-building-enterprise-agents-with-agentcore `evaluators/mtg_eval/shared/llm_client.py` (MIT-0) | Token usage on the cost record; retryable model faults |
| `infra/constructs/src/agentcore_constructs/front_door.py` | SOCIAL `infra/stacks/social_intelligence_stack.py` (PITR, RETAIN); AGENT-PLATFORM (HTTP API + JWT) | Two tables, JWT HTTP API, `PutItem` only on audit, runtime invoke scoped to named ARNs |
| `infra/constructs/src/agentcore_constructs/networking.py` | ENTERPRISE `stacks/networking_stack.py`; FAST `docs/DEPLOYMENT.md` | Private-with-egress, 443-only SG, the full endpoint list, org-scoped AgentCore endpoint policy, SSM parameters |
| `infra/constructs/src/agentcore_constructs/networking.py` (DNS Firewall) | DNS-FW `examples/dns_firewall_example.py` | `CfnFirewallDomainList`, rule group, association with mutation protection, query logging, blocked-queries metric and alarm. Allow-list then block `*` (the sample blocked named bad domains; DNS lookups have been used to move data out) |
| `infra/constructs/src/agentcore_constructs/observability.py` | ENTERPRISE `stacks/observability_stack.py` (lines 204 to 370) | SNS + email, SystemErrors / Throttles / p99, "Check first" descriptions, missing data not breaching, dashboard |
| `docs/ops/operating-model.md` | ENTERPRISE `docs/OPERATING_MODEL.md` | Owner roles, on-call, escalation, RACI; TBD placeholders left in |

## Where no AgentCore reference exists

The references name an AWS document or a non-AgentCore sample for these gaps. Each file cites it.

| This repo | Reference used |
| --- | --- |
| `infra/rotation/handler.py`, `RotationFunction` in `foundation.py` | AWS CDK `secret.add_rotation_schedule` docs; Secrets Manager rotation function template |
| `scripts/sign-and-sbom.sh` | ECR managed signing docs (`put-signing-configuration`, `describe-image-signing-status`); `notation verify`; Inspector `create-sbom-export` docs |
| `.trivyignore.yaml` and the Trivy step | Trivy as the pipeline image gate. The reference was BOISE `.github/workflows/nightly.yml`, which cannot be copied (below); Trivy's own documented flags are used instead |
| `infra/constructs/src/agentcore_constructs/model_profile.py` | Bedrock user guide, "Create an application inference profile" (`AWS::Bedrock::ApplicationInferenceProfile`, `ModelSource.CopyFrom`). Team tag in the spirit of LOOM's group tag | Per-agent model key; no AgentCore repo creates application inference profiles |
| `infra/constructs/.../networking.py` Code Interpreter | `AWS::BedrockAgentCore::CodeInterpreterCustom` (CloudFormation); docs/design/library.md "Code the model wrote" | VPC mode with its own role, behind the DNS Firewall |

## Step 5: policy Q&A

| This repo | Source | What was taken |
| --- | --- | --- |
| `patterns/policy-qa/` (messy fixture set, source-backed score) | EVAL-FIRST | Deliberately messy policies so a wrong source fails; groundedness 0.7 |
| `patterns/policy-qa/agent/policy_qa/knowledge.py` (tenant/role filter) | TENANCY | Filter from the verified login, not from the model |

## Step 6: human approval

| This repo | Source | What was taken |
| --- | --- | --- |
| `patterns/human-approval/` pause and token | `primitives/approvals` plus the library page (hook / tool context / Step Functions / MCP elicitation) | One pause, one token, one expiry; the approver cannot be the actor |
| `primitives/gateway-tools/submit_change/` | `_template` (`save_note`) | Idempotent conditional put, double-invoke test |

## Step 7: ambient

| This repo | Source | What was taken |
| --- | --- | --- |
| `patterns/ambient/agent/ambient/jobs.py` | docs/design/library.md "Job queue" and "Idempotency" | Conditional put on source plus event id; job status including `waiting_for_approval` |

## Step 8: catalogue

No production files were copied in this step. `docs/catalog.md` is original. It cites [Anthropic, Building effective agents](https://www.anthropic.com/engineering/building-effective-agents), the same link already on the library page. The 8 October coverage-review tables stay as the gap list that drove the stack; a 9 October snapshot sits above them.

`templates/human-in-the-loop/` is deleted. Use `patterns/human-approval/`.

## BOISE substitutions

BOISE is PolyForm Noncommercial. Nothing was copied from it. Where the references point at BOISE, this repo uses the following instead:

| Reference item | BOISE file | Used instead |
| --- | --- | --- |
| 2. Digest pins, multi-stage, `uv sync --frozen`, non-root, `HEALTHCHECK` | `backend/Dockerfile.inference-api` | FAST Dockerfile shape plus Docker's documented `FROM image@sha256` pinning |
| 7. OTel env vars that keep prompts out of spans | `backend/Dockerfile.inference-api` | `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=false` from the OpenTelemetry GenAI semantic conventions |
| 2. Trivy pipeline gate | `.github/workflows/nightly.yml` | Trivy CLI flags (`--severity HIGH,CRITICAL --ignore-unfixed --exit-code 1`) |

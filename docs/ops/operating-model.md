# Operating model

Status: **DRAFT — named owners required before a production deploy**

Copied from aws-samples/sample-agentcore-enterprise-platform `docs/OPERATING_MODEL.md` (Apache-2.0): owner roles, on-call, escalation, and a RACI template, with TBD placeholders to fill in. See [third-party.md](../attribution/third-party.md). This page is the library's copy. It does not assign a person, grant access, or accept risk.

Replace every `[TBD]` with a named role, a person or group, and a durable contact. Do not put account ids, private phone numbers, or credentials in this repository.

## Document control

| Field | Value |
| --- | --- |
| Service | AgentCore pattern library (this repository) |
| Environments | `dev`, `prod` (`config/environments/`) |
| Service owner | `[TBD: named person and durable role]` |
| Document owner | `[TBD]` |
| Effective and review dates | `[TBD: ISO-8601]` |
| Authoritative record | `[TBD: the customer's system, not git]` |
| Approval status | `DRAFT — not approved` |

## Named roles

Use durable groups for paging. Name one accountable person for decisions.

| Role | Named person / group | Responsibilities | Coverage / delegate | Contact |
| --- | --- | --- | --- | --- |
| Product owner | `[TBD]` | Outcome, scope, claims, funding, residual-risk acceptance | `[TBD]` | `[TBD]` |
| Service owner | `[TBD]` | End-to-end health, SLOs, launch readiness | `[TBD]` | `[TBD]` |
| Platform / library owner | `[TBD]` | Primitives, front door, CDK constructs, environment files | `[TBD]` | `[TBD]` |
| Pattern owner | `pattern.yaml` `owner` | That pattern's prompts, tools, evals, and release | `[TBD]` | `alert_route` in the same file |
| Security owner | `[TBD]` | Threat model, IAM, authorization, findings | `[TBD]` | `[TBD]` |
| Identity owner | `[TBD]` | IdP, JWT issuer/audience, on-behalf-of providers | `[TBD]` | `[TBD]` |
| Operations / on-call | `[TBD]` | Alarms, runbooks, incidents, capacity | `[TBD]` | SNS email in `observability.alarm_email` |
| Release owner | `[TBD]` | Build, scan, deploy, rollback, evidence | `[TBD]` | `[TBD]` |
| Agent quality owner | `[TBD]` | Golden set, thresholds, regressions | `[TBD]` | `[TBD]` |

Every alarm description ends with `Runbook: <runbook_url> Owner: <owner>` from the pattern manifest. That is the copy from ENTERPRISE `use-cases/_template/manifest.yaml`, plus `alert_route` and `runbook_url` which no AgentCore repo had.

## On-call

| Decision | Value |
| --- | --- |
| Support hours | `[TBD]` |
| Primary and secondary | `[TBD]` |
| Paging | SNS topic `<prefix>-alarms`. Email subscription does nothing until the confirmation link is clicked. |
| Intake | The alarm, then the "Check first" hint in its description |
| Severity | `[TBD: align with the customer incident policy]` |
| Ack and engage targets | `[TBD]` |
| Security incident route | `[TBD]` |
| AWS escalation | `[TBD]` |

Alarms (ENTERPRISE `stacks/observability_stack.py`): SystemErrors over two periods, Throttles, p99 Latency over 15 minutes, all in `AWS/Bedrock-AgentCore`. Missing data is not breaching. Alarm and OK both go to the topic. The front door's chat/job Lambdas and the HTTP API have the same treatment. DNS Firewall blocked queries page on a name outside the allow-list.

## Escalation

| Trigger | First | Then | Accountable |
| --- | --- | --- | --- |
| Runtime SystemErrors / total outage | On-call | Platform | Service owner |
| Front door 5xx | On-call | Platform (chat Lambda logs) | Service owner |
| Authentication failure | On-call | Identity | Security |
| Kill switch pulled | The person who pulled it | Pattern owner | Service owner |
| Quota or spend cap | On-call | Pattern owner | Product owner |
| Suspected data leaving the VPC (DNS BLOCK) | On-call | Security | Security |
| Failed release | Release owner | Platform | Service owner |

Runbooks: [any runtime](../runbooks/README.md), [kill switch](../runbooks/kill-switch.md), [quotas](../runbooks/quotas.md).

## RACI

R = Responsible, A = Accountable, C = Consulted, I = Informed. Each row has exactly one A.

| Activity | Product | Service | Platform | Security | Identity | Operations | Pattern owner | Release |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Front door, quotas, kill switch | C | A | R | C | C | C | I | I |
| Runtime alarms and dashboard | I | A | C | C | I | R | C | I |
| Pattern prompts, tools, evals | C | A | I | C | I | I | R | C |
| Identity (issuer, audience, OBO) | I | C | C | C | A | I | I | I |
| Network, DNS Firewall, Code Interpreter VPC | I | C | R | A | I | C | I | I |
| Change approval / production promotion | C | A | R | C | C | C | C | R |
| Incident command | I | A | C | C | C | R | C | C |
| Kill switch during an incident | I | A | C | C | I | R | C | I |
| Rollback of a named endpoint | I | A | C | I | I | C | C | R |

This matrix is a draft. It is not an assignment.

## Change and release

No change is approved solely because its code merged. A ship verdict is `PASS` or `PASS+NOTES` from a **different** process that re-runs the Runtime eval. This repository has no live Runtime PASS.

| Class | Examples | Checks | Approver | Rollback |
| --- | --- | --- | --- | --- |
| Standard | Docs, eval fixtures | `ruff`, `mypy`, `pytest -m "not runtime"` | `[TBD]` | Revert the PR |
| Normal | Agent, front door, environment quotas | The PR checks, then `scripts/deploy.sh` | `[TBD]` | Point the named endpoint at the previous version ([runbook](../runbooks/README.md#rollback)) |
| High-risk | Identity, KMS, DNS allow-list, kill-switch off | Normal plus security review | `[TBD]` | Tested rollback |
| Emergency | Active incident | Minimum safe checks, incident link | `[TBD: incident commander]` | Kill switch, then rollback |

Automatic alarm-driven rollback is not built. Deploy a new version to a canary endpoint, watch these alarms, then point `prod` at it or not.

## Routines

| Cadence | Routine | Owner |
| --- | --- | --- |
| Continuous | Alarms, audit rows, cost records | Operations |
| Per shift | Health, refused calls, open incidents | On-call |
| Per release | `agentcore-kit verify` including MMDSv2 and the front-door-only invoke policy | Release |
| Monthly | Quotas vs actuals, secret rotation, access review | `[TBD]` |
| `[TBD]` | Restore exercise of the front-door tables (PITR is on; a scheduled restore test is not) | `[TBD]` |

## What is not filled in yet

Named people, paging hours, severity, the customer incident system, and a production Runtime PASS. The guardrail **service** control is still off in `config/environments/prod.yaml`, so `agentcore-kit production-check` still refuses a production deploy.

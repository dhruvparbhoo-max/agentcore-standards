# agentcore-constructs

CDK constructs a pattern's `infra/app.py` uses. The AgentCore CLI still deploys the runtime, memory, gateway, and endpoints. These constructs own everything around that: secrets, the front door, the network, alarms, and the per-agent model key.

- `PatternFoundation`: customer-managed KMS key with rotation, ECR (scan on push, keep last 10), log group (retention 30/90/180/365, data protection policy), one secret per name under the environment prefix.
- `FrontDoor`: state and audit DynamoDB tables (PITR; audit is append-only), the session-binding secret, two ARM64 Lambda functions from `primitives/front-door/Dockerfile`, an HTTP API with a JWT authorizer. The role may `PutItem` on the audit table and nothing else, and `InvokeAgentRuntime` only on the runtimes it fronts.
- `NetworkFoundation`: VPC with private-with-egress subnets, 443-only runtime security group, the FAST endpoint list, Route 53 Resolver DNS Firewall (allow-list then block everything else), optional Code Interpreter in VPC mode.
- `RuntimeAlarms`: SNS topic, per-runtime SystemErrors / Throttles / p99 with "Check first" descriptions, dashboard. `add_function` / `add_http_api` cover the front door.
- `AgentModelProfile`: an application inference profile per model, tagged with the team. Invoke is granted through those profiles only.
- `grant_secret_read(name, grantee)`: read access to one secret for one role.
- `unmask_policies()`: managed policies that allow or deny `logs:Unmask` on the pattern's log group only.
- `RotationFunction`: the container-image rotation Lambda for secrets the platform can reissue itself.

`removal_for(environment)` returns `DESTROY` in a development environment and `RETAIN` everywhere else.

Sources are listed in `docs/attribution/third-party.md`. Nothing here has been deployed to AWS.

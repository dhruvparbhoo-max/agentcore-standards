# agentcore-constructs

CDK constructs a pattern's `infra/app.py` uses before the AgentCore CLI deploys the runtime.

- `PatternFoundation`: one customer-managed KMS key with rotation, one ECR repository (scan on push, keep the last 10 images), one log group (retention from the environment file, a CloudWatch Logs data protection policy that masks email addresses, IP addresses, and the pattern's custom identifiers), and one Secrets Manager secret per name under the environment prefix.
- `grant_secret_read(name, grantee)`: read access to one secret for one role. The runtime role gets no secret unless a pattern asks.
- `unmask_policies()`: managed policies that allow or deny `logs:Unmask` on the pattern's log group only.
- `RotationFunction`: the container-image rotation Lambda for secrets the platform can reissue itself.

`removal_for(environment)` returns `DESTROY` in a development environment and `RETAIN` everywhere else.

Sources are listed in `docs/attribution/third-party.md`.

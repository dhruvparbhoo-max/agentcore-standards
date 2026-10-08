# agentcore-identity

Actor and session headers (DESIGN §2.8). Version 0.1.0.

`require_actor_id` reads `X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id`, then `x-agentcore-actor-id`. The workload user header is a different IAM action and does not fill in the actor. A missing actor raises `ActorMissing`.

`require_session_id` reads the context session id and `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`. Two different values raise `SessionMismatch`.

Session lifecycle stays in the `agentcore-session` stub. This package only reads headers.

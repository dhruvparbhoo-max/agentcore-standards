# Quotas and spend caps

The front door counts **before** it starts a Runtime session. Over quota, the call is refused (`quota_exceeded` or `cap_reached`) and an `refused` audit row is written. Nothing inside the agent can bypass this: the agent is not invoked.

Daily and per-minute limits live in `config/environments/<env>.yaml` under `front_door.quotas`. Monthly spend for a user or a team lives next to them (`user_monthly_usd`, `team_monthly_usd`). The pattern's own monthly cap and per-run cap live in `pattern.yaml` (`cost.monthly_cap_usd`, `cost.max_usd_per_run`). Turns per session are `lifecycle.max_turns`.

The counter shape follows aws-samples/sample-agent-platform-with-agentcore `backend/app/services/governance_service.py` (MIT-0): one atomic increment per key, with a TTL on the daily and per-minute windows.

## What each limit means

| Limit | Key | Window | Default (dev / prod) |
| --- | --- | --- | --- |
| `user_daily` | the verified user id | calendar day UTC | 200 / 200 |
| `team_daily` | the team claim | calendar day UTC | 2000 / 2000 |
| `agent_daily` | the pattern name | calendar day UTC | 5000 / 10000 |
| `user_per_minute` | the verified user id | the current minute | 10 / 10 |
| `user_monthly_usd` | the verified user id | calendar month UTC | 20 / 50 |
| `team_monthly_usd` | the team claim | calendar month UTC | 200 / 1000 |
| `cost.monthly_cap_usd` | the agent | calendar month UTC | from `pattern.yaml` |
| `lifecycle.max_turns` | the session id | the session | from `pattern.yaml` |

Zero on a quota means that limit is off. Do not set production quotas to zero.

Prices are `front_door.prices` in the environment file, USD per million tokens, keyed by the geographic profile id (`eu.…`). A per-agent application inference profile is aliased to that id so the cost record still prices the call. A model with no price is recorded as `unpriced` at $0, not guessed.

## Check first

1. The refused audit row. `quota_exceeded` names the key that tripped (`user_daily`, `team_daily`, `agent_daily`, `user_per_minute`). `cap_reached` names the spend cap (`user_monthly_usd`, `team_monthly_usd`, `monthly_cap_usd`) or `max_turns`.
2. Whether this is one caller or everyone. One user at `user_per_minute` is a noisy client or a retry loop. The whole agent at `agent_daily` is load. A team at `team_monthly_usd` is a spend problem, not a bug.
3. The cost records for the month (`pk` `cost#YYYY-MM`). If they are `unpriced`, the environment file is missing that model id — fix the price list, do not raise the cap.
4. Throttles on `InvokeAgentRuntime`. The AgentCore runtime quota is separate. Raising the front-door limit will not help if the runtime itself is throttling.

## What to change

Quotas are environment config. Change `config/environments/<env>.yaml`, review it, and redeploy the **edge** stack so the Lambda environment picks up `FRONT_DOOR_SETTINGS`. Do not edit a counter row by hand.

A single user who is blocked until tomorrow needs a product decision, not a table write. Do not delete audit rows to "reset" a quota; the audit table denies `DeleteItem` and `UpdateItem` to every principal.

On a true incident (a runaway agent spending money), pull the [kill switch](kill-switch.md) for that agent first. Then lower `agent_daily` or `monthly_cap_usd` and redeploy.

## What this does not do

It does not replace Bedrock account quotas, AgentCore session quotas, or API Gateway throttle (`front_door.throttle` on the HTTP API). Those still apply. It does not refund a completed call: spend is counted from the usage the agent reports after the turn.

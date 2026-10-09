"""Quotas, rate limits, kill switches, and the turn and spend caps.

``check_and_count`` follows ``GovernanceService.check_and_count`` in
aws-samples/sample-agent-platform-with-agentcore
``backend/app/services/governance_service.py`` (MIT-0): a disabled source is
refused, atomic per-day counters increment before the call runs, and the call
is refused when a counter passes its limit. A failed model call still used
capacity. Added here: team and agent counters, a per-minute user rate, kill
switches per agent and per tool, the per-session turn cap, and monthly spend.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from agentcore_front_door.caller import VerifiedCaller
from agentcore_front_door.policy import AgentPolicy, DoorSettings
from agentcore_front_door.store import AGENT, SOURCE, TOOL, Store

_DAY_S = 2 * 86400
_MINUTE_S = 180
_MONTH_S = 40 * 86400


class Refused(Exception):
    """The call does not start. ``code`` is stable for clients and the audit trail."""

    status = 429

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class QuotaExceeded(Refused):
    status = 429


class SwitchedOff(Refused):
    status = 503


class CapReached(Refused):
    status = 429


@dataclass(frozen=True)
class Windows:
    day: str
    minute: str
    month: str
    epoch_s: int

    @classmethod
    def at(cls, now: datetime) -> Windows:
        moment = now.astimezone(UTC)
        return cls(
            day=moment.strftime("%Y-%m-%d"),
            minute=moment.strftime("%Y-%m-%dT%H:%M"),
            month=moment.strftime("%Y-%m"),
            epoch_s=int(moment.timestamp()),
        )


def check_switches(store: Store, *, agent: str, tools: Iterable[str], source: str) -> None:
    """Refuse when the agent, any tool it may call, or the calling source is switched off."""
    checks = [(SOURCE, source), (AGENT, agent), *((TOOL, tool) for tool in tools)]
    for scope, name in checks:
        switch = store.switch(scope, name)
        if switch is not None and not switch.enabled:
            reason = f": {switch.reason}" if switch.reason else ""
            raise SwitchedOff(f"{scope}_off", f"{scope} {name} is switched off{reason}")


def check_spend(store: Store, caller: VerifiedCaller, policy: AgentPolicy, settings: DoorSettings, w: Windows) -> None:
    """``cost.on_cap: pause``. A spent monthly cap stops new calls for the agent, the user, or the team."""
    caps = [(f"spend#agent#{policy.agent}#{w.month}", policy.monthly_cap_usd, "agent")]
    if settings.user_monthly_usd:
        caps.append((f"spend#user#{caller.user_id}#{w.month}", settings.user_monthly_usd, "user"))
    if settings.team_monthly_usd and policy.team:
        caps.append((f"spend#team#{policy.team}#{w.month}", settings.team_monthly_usd, "team"))
    for key, cap, label in caps:
        if cap and store.read(key) >= cap:
            raise CapReached(f"{label}_monthly_spend", f"{label} monthly spend cap of {cap:.2f} USD reached")


def check_and_count(
    store: Store, caller: VerifiedCaller, policy: AgentPolicy, settings: DoorSettings, w: Windows
) -> None:
    """Count this call against every limit, then refuse if one is passed."""
    quotas = settings.quotas
    day_ttl = w.epoch_s + _DAY_S
    counters = [
        (f"rate#user#{caller.user_id}#{w.minute}", quotas.user_per_minute, w.epoch_s + _MINUTE_S, "user_rate"),
        (f"quota#user#{caller.user_id}#{w.day}", quotas.user_daily, day_ttl, "user_daily"),
        (f"quota#agent#{policy.agent}#{w.day}", quotas.agent_daily, day_ttl, "agent_daily"),
    ]
    if policy.team:
        counters.append((f"quota#team#{policy.team}#{w.day}", quotas.team_daily, day_ttl, "team_daily"))
    for key, limit, ttl, code in counters:
        total = store.increment(key, ttl_epoch_s=ttl)
        if limit and total is not None and total > limit:
            raise QuotaExceeded(code, f"{code.replace('_', ' ')} limit of {limit} reached")


def count_turn(store: Store, session_id: str, policy: AgentPolicy, w: Windows) -> int:
    """Add one turn to the session. Refuse at ``max_turns``; the caller starts a new session."""
    total = store.increment(f"turns#{session_id}", ttl_epoch_s=w.epoch_s + _DAY_S, limit=float(policy.max_turns))
    if total is None:
        raise CapReached("session_turns", f"this session reached its cap of {policy.max_turns} turns")
    return int(total)


def add_spend(store: Store, caller: VerifiedCaller, policy: AgentPolicy, usd: float, w: Windows) -> None:
    if usd <= 0:
        return
    ttl = w.epoch_s + _MONTH_S
    store.increment(f"spend#agent#{policy.agent}#{w.month}", by=usd, ttl_epoch_s=ttl)
    store.increment(f"spend#user#{caller.user_id}#{w.month}", by=usd, ttl_epoch_s=ttl)
    if policy.team:
        store.increment(f"spend#team#{policy.team}#{w.month}", by=usd, ttl_epoch_s=ttl)

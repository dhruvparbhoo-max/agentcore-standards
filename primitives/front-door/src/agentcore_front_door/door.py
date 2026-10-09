"""``FrontDoor.call``: the one way to start a Runtime session.

The order is docs/design/library.md "Front door", steps 1 to 9. One change:
kill switches are read before quotas count, so a switched-off agent does not
use up anyone's quota. The accepted audit row is written before Runtime is
called; if it cannot be written, the call does not start. The shape of the
pipeline (one function every source funnels through, governance before the
invoke) follows ``invoke`` in aws-samples/sample-agent-platform-with-agentcore
``backend/app/services/invocation_service.py`` (MIT-0).
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from agentcore_front_door import governance
from agentcore_front_door.caller import USER, VerifiedCaller
from agentcore_front_door.cost import Cost, Usage, price_usage
from agentcore_front_door.governance import Refused, Windows
from agentcore_front_door.obo import OboExchanger, OboTokens
from agentcore_front_door.policy import AgentPolicy, DoorSettings
from agentcore_front_door.runtime import RuntimeFailed, RuntimeInvoker
from agentcore_front_door.sessions import SessionBinder, SessionRejected
from agentcore_front_door.store import AuditWriteFailed, Store

log = logging.getLogger("agentcore_front_door")

SOURCES = ("chat", "api", "job", "schedule", "event", "eval")


class UnknownAgent(Refused):
    status = 404


class NeedsUser(Refused):
    status = 403


class BadSession(Refused):
    status = 400


class SessionBusy(Refused):
    status = 409


class AuditUnavailable(Refused):
    status = 503


@dataclass(frozen=True)
class CallRequest:
    caller: VerifiedCaller
    agent: str
    payload: Mapping[str, Any]
    source: str = "chat"
    session_id: str | None = None
    job_id: str = ""


@dataclass(frozen=True)
class CallResult:
    call_id: str
    session_id: str
    status_code: int
    body: Mapping[str, Any]
    release_id: str
    turn: int
    cost: Cost
    usage: Usage
    breaches: tuple[str, ...] = ()
    audit_complete: bool = True
    extra: Mapping[str, Any] = field(default_factory=dict)


class FrontDoor:
    def __init__(
        self,
        *,
        policies: Mapping[str, AgentPolicy],
        settings: DoorSettings,
        store: Store,
        binding_secret: bytes,
        invoker: RuntimeInvoker,
        exchanger: OboExchanger | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.policies = dict(policies)
        self.settings = settings
        self.store = store
        self._secret = binding_secret
        self.invoker = invoker
        self.exchanger = exchanger
        self._now = now

    def binder(self, policy: AgentPolicy) -> SessionBinder:
        return SessionBinder(self._secret, min_length=policy.session_id_min)

    def call(self, request: CallRequest) -> CallResult:
        call_id = uuid.uuid4().hex
        moment = self._now()
        w = Windows.at(moment)
        policy = self.policies.get(request.agent)
        context: dict[str, Any] = {"call_id": call_id, "request": request, "policy": policy, "moment": moment}
        try:
            policy, session_id = self._admit(request, policy)
        except Refused as refusal:
            self._refused(context, refusal)
            raise
        context["session_id"] = session_id

        expires = w.epoch_s + policy.timeout_s + self.settings.lease_grace_s
        if not self.store.acquire_lease(session_id, holder=call_id, now_s=w.epoch_s, expires_s=expires):
            busy = SessionBusy("session_busy", "another call is still running in this session")
            self._refused(context, busy)
            raise busy
        try:
            return self._run(request, policy, session_id, call_id, moment, w, context)
        finally:
            self.store.release_lease(session_id, holder=call_id)

    def _admit(self, request: CallRequest, policy: AgentPolicy | None) -> tuple[AgentPolicy, str]:
        if request.source not in SOURCES:
            raise BadSession("bad_source", f"source must be one of {SOURCES}")
        if policy is None:
            raise UnknownAgent("unknown_agent", f"no agent named {request.agent}")
        if policy.acts_as == USER and request.caller.kind != USER and not request.caller.on_behalf_of:
            raise NeedsUser("needs_user", "this agent acts as a signed-in user")
        try:
            return policy, self.binder(policy).resolve(request.caller.user_id, request.session_id)
        except SessionRejected as exc:
            raise BadSession("bad_session", str(exc)) from exc

    def _run(
        self,
        request: CallRequest,
        policy: AgentPolicy,
        session_id: str,
        call_id: str,
        moment: datetime,
        w: Windows,
        context: dict[str, Any],
    ) -> CallResult:
        try:
            governance.check_switches(self.store, agent=policy.agent, tools=policy.tools, source=request.source)
            governance.check_spend(self.store, request.caller, policy, self.settings, w)
            governance.check_and_count(self.store, request.caller, policy, self.settings, w)
            turn = governance.count_turn(self.store, session_id, policy, w)
            context["turn"] = turn
            obo = self.exchanger.exchange(request.caller, policy) if self.exchanger else OboTokens()
            if not policy.runtime_arn:
                raise Refused("not_deployed", f"agent {policy.agent} has no runtime configured")
            try:
                self.store.append_audit(self._entry(context, "accepted", "accepted", obo=obo))
            except AuditWriteFailed as exc:
                raise AuditUnavailable("audit_unavailable", "the audit trail is unavailable") from exc
        except Refused as refusal:
            self._refused(context, refusal)
            raise

        started = time.perf_counter()
        outcome = "ok"
        status_code = 200
        body: Mapping[str, Any] = {}
        try:
            reply = self.invoker.invoke(
                runtime_arn=policy.runtime_arn,
                qualifier=policy.endpoint,
                session_id=session_id,
                actor_id=request.caller.user_id,
                payload=request.payload,
                obo=obo,
            )
            status_code, body = reply.status_code, reply.body
        except RuntimeFailed as exc:
            outcome, status_code = exc.code, 502
            body = {"error": "runtime_failed", "code": exc.code}
        latency_ms = round((time.perf_counter() - started) * 1000, 1)

        usage = Usage.from_reply(body)
        cost = price_usage(usage, self.settings.prices, aliases=policy.model_aliases)
        breaches: list[str] = []
        if usage.model_calls > policy.max_steps:
            breaches.append("steps")
        if cost.usd > policy.max_usd_per_run:
            breaches.append("run_spend")
        governance.add_spend(self.store, request.caller, policy, cost.usd, w)
        release_id = str(body.get("release_id") or policy.release_id or "unreleased")
        context.update(
            release_id=release_id,
            latency_ms=latency_ms,
            usage=usage,
            cost=cost,
            breaches=tuple(breaches),
            outcome=outcome,
        )
        complete = self._write_completion(context, obo)
        if breaches:
            log.warning("cap breach", extra={"call_id": call_id, "agent": policy.agent, "breaches": breaches})
        return CallResult(
            call_id=call_id,
            session_id=session_id,
            status_code=status_code,
            body=body,
            release_id=release_id,
            turn=turn,
            cost=cost,
            usage=usage,
            breaches=tuple(breaches),
            audit_complete=complete,
        )

    def _write_completion(self, context: dict[str, Any], obo: OboTokens) -> bool:
        try:
            self.store.append_audit(self._entry(context, "completed", context["outcome"], obo=obo))
            self.store.append_audit(self._cost_record(context))
        except AuditWriteFailed:
            log.error("audit completion not written", extra={"call_id": context["call_id"]})
            return False
        return True

    def _refused(self, context: dict[str, Any], refusal: Refused) -> None:
        try:
            self.store.append_audit(self._entry(context, "refused", refusal.code))
        except AuditWriteFailed:
            log.error("refusal not audited", extra={"call_id": context["call_id"], "code": refusal.code})

    def _entry(
        self, context: dict[str, Any], phase: str, outcome: str, *, obo: OboTokens | None = None
    ) -> dict[str, Any]:
        request: CallRequest = context["request"]
        policy: AgentPolicy | None = context["policy"]
        moment: datetime = context["moment"]
        caller = request.caller
        usage: Usage | None = context.get("usage")
        cost: Cost | None = context.get("cost")
        stamp = moment.astimezone(UTC).isoformat()
        entry: dict[str, Any] = {
            "pk": f"audit#{moment.astimezone(UTC).strftime('%Y-%m-%d')}",
            "sk": f"{stamp}#{context['call_id']}#{phase}",
            "kind": "audit",
            "phase": phase,
            "outcome": outcome,
            "call_id": context["call_id"],
            "at": stamp,
            "user": caller.user_id,
            "caller_kind": caller.kind,
            "team": caller.team,
            "tenant": caller.tenant,
            "consent_ref": caller.consent_ref,
            "on_behalf_of": caller.on_behalf_of,
            "agent": request.agent,
            "source": request.source,
            "job_id": request.job_id,
            "session": _digest(context.get("session_id", "")),
            "release_id": context.get("release_id") or (policy.release_id if policy else ""),
            "endpoint": policy.endpoint if policy else "",
            "turn": int(context.get("turn", 0)),
        }
        if obo is not None and obo.providers:
            entry["obo_providers"] = list(obo.providers)
        if phase == "completed" and usage is not None and cost is not None:
            entry.update(
                latency_ms=context["latency_ms"],
                model_calls=usage.model_calls,
                usd=cost.usd,
                cost_source=cost.source,
                breaches=list(context.get("breaches", ())),
            )
        return entry

    def _cost_record(self, context: dict[str, Any]) -> dict[str, Any]:
        request: CallRequest = context["request"]
        policy: AgentPolicy = context["policy"]
        usage: Usage = context["usage"]
        cost: Cost = context["cost"]
        moment: datetime = context["moment"]
        stamp = moment.astimezone(UTC).isoformat()
        return {
            "pk": f"cost#{moment.astimezone(UTC).strftime('%Y-%m')}",
            "sk": f"{stamp}#{context['call_id']}",
            "kind": "cost",
            "call_id": context["call_id"],
            "at": stamp,
            "agent": policy.agent,
            "team": policy.team,
            "user": request.caller.user_id,
            "release_id": context["release_id"],
            "model": usage.model,
            "model_calls": usage.model_calls,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "usd": cost.usd,
            "source": cost.source,
        }


def _digest(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16] if session_id else ""

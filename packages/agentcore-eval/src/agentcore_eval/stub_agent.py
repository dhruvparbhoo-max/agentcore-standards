"""Deterministic stand-in for the business golden suite.

The handler executes an allowlisted tool from the turn payload. It is how the
suite runs offline. It is not a model and it is not AgentCore Runtime.
"""

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from agentcore_eval.hitl import ApprovalStatus, InMemoryHitlGate
from agentcore_eval.memory import InMemoryRuntimeHarness

_CENT = Decimal("0.01")
_ALLOW = frozenset({"invoice.lookup", "invoice.record_payment", "crm.lookup_account", "approve.payment"})


class _Invoice:
    def __init__(self, *, status: str, balance: Decimal, customer: str, account_id: str) -> None:
        self.status = status
        self.balance = balance
        self.customer = customer
        self.account_id = account_id


def _seed(status: str, balance: str, customer: str, account_id: str) -> _Invoice:
    return _Invoice(status=status, balance=Decimal(balance), customer=customer, account_id=account_id)


_SEED = {
    "INV-1042": _seed("open", "1250.00", "Northwind Traders", "acct-100"),
    "INV-1043": _seed("paid", "0.00", "Contoso", "acct-200"),
}
_ACCOUNTS = {
    "acct-100": ("Northwind Traders", "ap-clerk"),
    "acct-200": ("Contoso", "sales"),
}


class BusinessStub:
    """Invoice, CRM, and approval tools with per-session books and idempotent payments."""

    def __init__(self, gate: InMemoryHitlGate | None = None) -> None:
        self._gate = gate or InMemoryHitlGate()
        self._books: dict[str, dict[str, _Invoice]] = {}
        self._payments: dict[tuple[str, str], dict[str, Any]] = {}

    def __call__(
        self,
        payload: Mapping[str, Any],
        *,
        session_id: str,
        actor_id: str,
        agent_version: str,
    ) -> dict[str, Any]:
        del actor_id, agent_version
        tool = payload.get("tool")
        if not isinstance(tool, str) or not tool:
            raise ValueError("business stub payload is missing tool")
        raw_args = payload.get("args", {})
        if not isinstance(raw_args, Mapping):
            raise ValueError("business stub args must be an object")
        if tool not in _ALLOW:
            return _output(
                status="denied",
                result=f"Tool {tool} is not allowed.",
                tool_calls=(),
                replayed=False,
                balance=None,
            )
        if tool == "invoice.lookup":
            return self._lookup(session_id, raw_args)
        if tool == "invoice.record_payment":
            return self._record(session_id, raw_args)
        if tool == "crm.lookup_account":
            return _crm(raw_args)
        return self._approve(session_id, raw_args)

    def _lookup(self, session_id: str, args: Mapping[str, Any]) -> dict[str, Any]:
        invoice_id = _require_str(args, "invoice_id")
        invoice = self._books_for(session_id).get(invoice_id)
        if invoice is None:
            return _output(
                status="not_found",
                result=f"Invoice {invoice_id} was not found.",
                tool_calls=("invoice.lookup",),
                replayed=False,
                balance=None,
            )
        balance = _format_money(invoice.balance)
        return _output(
            status="ok",
            result=f"Invoice {invoice_id} is {invoice.status} with a balance of {balance} USD.",
            tool_calls=("invoice.lookup",),
            replayed=False,
            balance=balance,
        )

    def _record(self, session_id: str, args: Mapping[str, Any]) -> dict[str, Any]:
        return self._pay(
            session_id,
            invoice_id=_require_str(args, "invoice_id"),
            amount=_money(args.get("amount")),
            idempotency_key=_require_str(args, "idempotency_key"),
            tool="invoice.record_payment",
            wording="recorded",
        )

    def _approve(self, session_id: str, args: Mapping[str, Any]) -> dict[str, Any]:
        invoice_id = _require_str(args, "invoice_id")
        amount = _money(args.get("amount"))
        approval_id = _require_str(args, "approval_id")
        now = _parse_time(args.get("now"), label="now")
        decision = args.get("decision")
        if decision is not None and decision not in {"approve", "deny"}:
            raise ValueError("decision must be approve or deny")
        invoice = self._books_for(session_id).get(invoice_id)
        if invoice is None:
            return _output(
                status="not_found",
                result=f"Invoice {invoice_id} was not found.",
                tool_calls=("approve.payment",),
                replayed=False,
                balance=None,
            )
        if not self._gate.known(approval_id):
            self._gate.request(
                approval_id=approval_id,
                action="approve.payment",
                subject=invoice_id,
                expires_at=_parse_time(args.get("expires_at"), label="expires_at"),
            )
        if decision == "approve":
            self._gate.decide(approval_id, approved=True, now=now)
        elif decision == "deny":
            self._gate.decide(approval_id, approved=False, now=now)
        approval = self._gate.check(approval_id, now=now)
        if approval.status is not ApprovalStatus.APPROVED:
            status = "expired" if approval.status is ApprovalStatus.EXPIRED else "blocked"
            return _output(
                status=status,
                result=f"Payment for {invoice_id} is {approval.status.value}.",
                tool_calls=("approve.payment",),
                replayed=False,
                balance=_format_money(invoice.balance),
            )
        return self._pay(
            session_id,
            invoice_id=invoice_id,
            amount=amount,
            idempotency_key=approval_id,
            tool="approve.payment",
            wording="approved",
        )

    def _pay(
        self,
        session_id: str,
        *,
        invoice_id: str,
        amount: Decimal,
        idempotency_key: str,
        tool: str,
        wording: str,
    ) -> dict[str, Any]:
        key = (session_id, idempotency_key)
        stored = self._payments.get(key)
        if stored is not None:
            replay = _copy(stored)
            replay["replayed"] = True
            replay["tool_calls"] = [tool]
            return replay
        invoice = self._books_for(session_id).get(invoice_id)
        if invoice is None:
            return _output(
                status="not_found",
                result=f"Invoice {invoice_id} was not found.",
                tool_calls=(tool,),
                replayed=False,
                balance=None,
            )
        if amount > invoice.balance:
            return _output(
                status="denied",
                result=f"Payment of {_format_money(amount)} USD exceeds the open balance of {invoice_id}.",
                tool_calls=(tool,),
                replayed=False,
                balance=_format_money(invoice.balance),
            )
        invoice.balance -= amount
        if invoice.balance == 0:
            invoice.status = "paid"
        balance = _format_money(invoice.balance)
        if wording == "approved":
            text = f"Payment for {invoice_id} is approved. Balance is {balance} USD."
        else:
            text = f"Recorded {_format_money(amount)} USD against {invoice_id}. Balance is {balance} USD."
        body = _output(status="ok", result=text, tool_calls=(tool,), replayed=False, balance=balance)
        self._payments[key] = body
        return _copy(body)

    def _books_for(self, session_id: str) -> dict[str, _Invoice]:
        books = self._books.get(session_id)
        if books is None:
            books = {
                invoice_id: _Invoice(
                    status=seed.status,
                    balance=seed.balance,
                    customer=seed.customer,
                    account_id=seed.account_id,
                )
                for invoice_id, seed in _SEED.items()
            }
            self._books[session_id] = books
        return books


def business_harness() -> InMemoryRuntimeHarness:
    """A fresh in-memory harness around a new ``BusinessStub``."""
    return InMemoryRuntimeHarness(BusinessStub())


def _crm(args: Mapping[str, Any]) -> dict[str, Any]:
    account_id = _require_str(args, "account_id")
    account = _ACCOUNTS.get(account_id)
    if account is None:
        return _output(
            status="not_found",
            result=f"Account {account_id} was not found.",
            tool_calls=("crm.lookup_account",),
            replayed=False,
            balance=None,
        )
    name, owner = account
    return _output(
        status="ok",
        result=f"Account {account_id} is {name}, owner {owner}.",
        tool_calls=("crm.lookup_account",),
        replayed=False,
        balance=None,
    )


def _output(
    *,
    status: str,
    result: str,
    tool_calls: tuple[str, ...],
    replayed: bool,
    balance: str | None,
) -> dict[str, Any]:
    return {
        "balance": balance,
        "replayed": replayed,
        "result": result,
        "status": status,
        "tool_calls": list(tool_calls),
    }


def _copy(body: Mapping[str, Any]) -> dict[str, Any]:
    tool_calls = body["tool_calls"]
    calls = list(tool_calls) if isinstance(tool_calls, list) else []
    return {
        "balance": body["balance"],
        "replayed": body["replayed"],
        "result": body["result"],
        "status": body["status"],
        "tool_calls": calls,
    }


def _require_str(args: Mapping[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value


def _money(value: object) -> Decimal:
    if not isinstance(value, str):
        raise ValueError("amount must be a decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("amount must be a decimal string") from exc
    if amount != amount.quantize(_CENT):
        raise ValueError("amount must have at most two decimal places")
    if amount <= 0:
        raise ValueError("amount must be positive")
    return amount


def _format_money(amount: Decimal) -> str:
    return f"{amount.quantize(_CENT):.2f}"


def _parse_time(value: object, *, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is required")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed

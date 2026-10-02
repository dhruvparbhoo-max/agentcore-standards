"""Invoice tools on the agentcore-tools registry.

Gateway fronts both tools. The policy starts empty and this module permits
only ``AGENT_VERSION``. A side-effecting note is idempotent twice: the registry
replays an idempotency key, and the handler put-if-absent keeps one row for
``(tenant, invoice, key)`` when Lambda is retried without that cache.

The catalog and the note map live in this process. A separate Lambda process
does not share them. Durable storage is the same natural key, not a second
tool protocol.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from agentcore_tools import (
    AgentCoreGatewayClient,
    FatalToolError,
    GatewaySyncResult,
    Policy,
    RetryableToolError,
    ToolRegistry,
    make_lambda_handler,
)
from agentcore_tools.lambda_target import Handler

from agent_with_tools.version import AGENT_VERSION

FETCH_INVOICE = "fetch_invoice"
SUBMIT_INVOICE_NOTE = "submit_invoice_note"
TARGET_NAME = "billing"
LOCAL_GATEWAY_ID = "billing-desk-local"
ALLOWED_TOOLS: tuple[str, ...] = (FETCH_INVOICE, SUBMIT_INVOICE_NOTE)

_FETCH_SCHEMA: dict[str, Any] = {
    "additionalProperties": False,
    "properties": {
        "invoice_id": {"description": "Invoice id, for example INV-1001.", "type": "string"},
        "tenant_id": {"description": "Tenant supplied by the caller context.", "type": "string"},
        "user_id": {"description": "User supplied by the caller context.", "type": "string"},
    },
    "required": ["invoice_id", "tenant_id", "user_id"],
    "type": "object",
}

_NOTE_SCHEMA: dict[str, Any] = {
    "additionalProperties": False,
    "properties": {
        "idempotency_key": {"description": "Key that stores this note once.", "type": "string"},
        "invoice_id": {"description": "Invoice id the note belongs to.", "type": "string"},
        "note": {"description": "Customer note text.", "type": "string"},
        "tenant_id": {"description": "Tenant supplied by the caller context.", "type": "string"},
        "user_id": {"description": "User supplied by the caller context.", "type": "string"},
    },
    "required": ["invoice_id", "note", "idempotency_key", "tenant_id", "user_id"],
    "type": "object",
}


@dataclass(frozen=True)
class Invoice:
    """One invoice row scoped to a tenant."""

    invoice_id: str
    tenant_id: str
    status: str
    amount: str
    currency: str
    customer: str


@dataclass(frozen=True)
class NoteRecord:
    """One stored note. The idempotency key is part of the identity."""

    tenant_id: str
    invoice_id: str
    idempotency_key: str
    note: str
    requested_by: str


# The same invoice id in two tenants has different amounts, so a tool that
# trusts the sentence instead of the caller context returns the wrong bill.
_CATALOG: dict[tuple[str, str], Invoice] = {
    ("acme", "INV-1001"): Invoice(
        invoice_id="INV-1001",
        tenant_id="acme",
        status="OPEN",
        amount="1250.00",
        currency="USD",
        customer="Northwind",
    ),
    ("acme", "INV-1002"): Invoice(
        invoice_id="INV-1002",
        tenant_id="acme",
        status="PAID",
        amount="80.00",
        currency="USD",
        customer="Contoso",
    ),
    ("globex", "INV-1001"): Invoice(
        invoice_id="INV-1001",
        tenant_id="globex",
        status="OPEN",
        amount="9999.00",
        currency="USD",
        customer="Restricted",
    ),
}


def normalize_invoice_id(invoice_id: str) -> str:
    """Trim and uppercase an invoice id. ``inv-1001`` and ``INV-1001`` match."""
    return invoice_id.strip().upper()


def looks_like_invoice_id(invoice_id: str) -> bool:
    """True when the id has the ``INV-`` shape the catalog uses."""
    cleaned = normalize_invoice_id(invoice_id)
    suffix = cleaned.removeprefix("INV-")
    return cleaned.startswith("INV-") and suffix.isdigit() and bool(suffix)


class BillingDesk:
    """Registry, allowlist, and the invoice handlers behind it."""

    def __init__(self) -> None:
        self.registry = ToolRegistry()
        self.policy = Policy()
        self._lock = threading.Lock()
        self._notes: dict[tuple[str, str, str], NoteRecord] = {}
        self._calls = {FETCH_INVOICE: 0, SUBMIT_INVOICE_NOTE: 0}
        self._retryable_reads = 0
        self._register()
        for name in ALLOWED_TOOLS:
            self.policy.permit(AGENT_VERSION, name)
        self.bind(_gateway_id_from_env())

    def bind(self, gateway_id: str) -> None:
        """Attach the live policy to ``gateway_id``. Rebinding replaces the id only."""
        self.registry.bind_gateway(gateway_id, policy=self.policy)
        self.gateway_id = gateway_id

    def call_count(self, name: str) -> int:
        """How many times the handler itself ran. Replays and denials stay at zero."""
        with self._lock:
            return self._calls[name]

    def note_count(self, tenant_id: str, invoice_id: str) -> int:
        """Stored notes for one invoice in one tenant."""
        wanted = (tenant_id.strip(), normalize_invoice_id(invoice_id))
        with self._lock:
            return sum(1 for key in self._notes if key[:2] == wanted)

    def fail_next_fetch(self) -> None:
        """Next read raises a retryable error once. The retry eval uses this seam."""
        with self._lock:
            self._retryable_reads += 1

    def _register(self) -> None:
        desk = self

        @self.registry.tool(
            name=FETCH_INVOICE,
            schema=_FETCH_SCHEMA,
            description="Read one invoice for the tenant in the arguments. The same id returns the same invoice.",
            idempotent=True,
            side_effecting=False,
            schema_version="1.0.0",
        )
        def fetch_invoice(args: Mapping[str, Any]) -> Mapping[str, Any]:
            return desk._fetch(args)

        @self.registry.tool(
            name=SUBMIT_INVOICE_NOTE,
            schema=_NOTE_SCHEMA,
            description="File one customer note. The same tenant, invoice, and idempotency key store one note.",
            idempotent=True,
            side_effecting=True,
            schema_version="1.0.0",
        )
        def submit_invoice_note(args: Mapping[str, Any]) -> Mapping[str, Any]:
            return desk._submit(args)

        self.registry.add_lambda_target(TARGET_NAME, tools=ALLOWED_TOOLS)

    def _fetch(self, args: Mapping[str, Any]) -> Mapping[str, Any]:
        with self._lock:
            self._calls[FETCH_INVOICE] += 1
            injected = self._retryable_reads > 0
            if injected:
                self._retryable_reads -= 1
        if injected:
            raise RetryableToolError("billing read failed", code="billing_unavailable")
        tenant_id, user_id, invoice_id = _identity(args)
        invoice = _CATALOG.get((tenant_id, invoice_id))
        if invoice is None:
            raise FatalToolError("invoice was not found for this tenant", code="invoice_not_found")
        return {
            "amount": invoice.amount,
            "currency": invoice.currency,
            "customer": invoice.customer,
            "invoice_id": invoice.invoice_id,
            "requested_by": user_id,
            "status": invoice.status,
            "tenant_id": invoice.tenant_id,
        }

    def _submit(self, args: Mapping[str, Any]) -> Mapping[str, Any]:
        with self._lock:
            self._calls[SUBMIT_INVOICE_NOTE] += 1
        tenant_id, user_id, invoice_id = _identity(args)
        if _CATALOG.get((tenant_id, invoice_id)) is None:
            raise FatalToolError("invoice was not found for this tenant", code="invoice_not_found")
        note = str(args["note"]).strip()
        key = str(args["idempotency_key"]).strip()
        if not note:
            raise FatalToolError("note text is required", code="empty_note")
        if not key:
            raise FatalToolError("idempotency key is required", code="missing_idempotency_key")
        record, duplicate = self._put_note(
            tenant_id=tenant_id,
            invoice_id=invoice_id,
            idempotency_key=key,
            note=note,
            requested_by=user_id,
        )
        return {
            "duplicate": duplicate,
            "idempotency_key": record.idempotency_key,
            "invoice_id": record.invoice_id,
            "note": record.note,
            "requested_by": record.requested_by,
            "tenant_id": record.tenant_id,
        }

    def _put_note(
        self,
        *,
        tenant_id: str,
        invoice_id: str,
        idempotency_key: str,
        note: str,
        requested_by: str,
    ) -> tuple[NoteRecord, bool]:
        identity = (tenant_id, invoice_id, idempotency_key)
        with self._lock:
            existing = self._notes.get(identity)
            if existing is not None:
                return existing, True
            record = NoteRecord(
                tenant_id=tenant_id,
                invoice_id=invoice_id,
                idempotency_key=idempotency_key,
                note=note,
                requested_by=requested_by,
            )
            self._notes[identity] = record
            return record, False


_desk: BillingDesk | None = None


def get_desk() -> BillingDesk:
    """Process-wide desk. The hosted agent and the Lambda handler share it."""
    global _desk
    if _desk is None:
        _desk = BillingDesk()
    return _desk


def reset_desk() -> BillingDesk:
    """Replace the desk so evals do not reuse an idempotency cache or a note."""
    global _desk
    _desk = BillingDesk()
    return _desk


def lambda_handler(event: Mapping[str, Any], context: Any) -> dict[str, Any]:
    """Gateway Lambda entrypoint. Policy has already run before this function."""
    handler: Handler = make_lambda_handler(get_desk().registry, agent_version=AGENT_VERSION)
    return handler(event, context)


def sync_billing_gateway() -> GatewaySyncResult:
    """Create the billing Lambda target and the Cedar permits for this version.

    Requires the Gateway environment names. The registry gateway id is rebound
    to ``AGENTCORE_GATEWAY_ID`` so it matches the client.
    """
    client = AgentCoreGatewayClient.from_env()
    gateway_id = os.environ["AGENTCORE_GATEWAY_ID"].strip()
    desk = get_desk()
    desk.bind(gateway_id)
    return client.sync(desk.registry, agent_version=AGENT_VERSION, target_name=TARGET_NAME)


def _gateway_id_from_env() -> str:
    configured = os.environ.get("AGENTCORE_GATEWAY_ID", "").strip()
    return configured or LOCAL_GATEWAY_ID


def _identity(args: Mapping[str, Any]) -> tuple[str, str, str]:
    tenant_id = str(args["tenant_id"]).strip()
    user_id = str(args["user_id"]).strip()
    invoice_id = normalize_invoice_id(str(args["invoice_id"]))
    if not tenant_id or not user_id:
        raise FatalToolError("tenant and user are required", code="missing_caller")
    if not looks_like_invoice_id(invoice_id):
        raise FatalToolError("invoice id is invalid", code="invalid_invoice_id")
    return tenant_id, user_id, invoice_id

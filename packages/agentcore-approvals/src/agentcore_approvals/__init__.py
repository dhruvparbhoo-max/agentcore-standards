"""Approval tokens. The actor who requests a tool cannot approve it."""

from agentcore_approvals.gate import ApprovalError, ApprovalGate, AuditRecord

__all__ = [
    "ApprovalError",
    "ApprovalGate",
    "AuditRecord",
]

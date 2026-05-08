"""Phase 3 — tamper-evident audit log with HMAC-SHA256 hash chain.

This sits beside the existing `audit_records` table (Slice 1's lightweight
event log used by the audit page). The new `audit_logs` table follows the
spec contract:
  - HMAC-SHA256 over (id | tenant_id | event_type | result | created_at | prev_hash)
  - prev_hash is the previous row's signed_hash for this tenant
  - First row's prev_hash = 'genesis'
  - Tampering with any row breaks the chain from that point onward
  - Chain integrity is verified by recomputing every row in order

Concurrent inserts for the same tenant are serialised via
pg_advisory_xact_lock(hashtextextended(tenant_id, 0)) — substituting for the
spec's Redis lock; equivalent guarantees, zero new infra.
"""

from tigeri.audit_chain.models import AuditLog
from tigeri.audit_chain.writer import (
    AuditChainBroken,
    AuditChainWriter,
    AuditEntry,
    verify_chain,
)

__all__ = [
    "AuditChainBroken",
    "AuditChainWriter",
    "AuditEntry",
    "AuditLog",
    "verify_chain",
]

"""R1-21: immutable revisions and approval binding (ADR-009).

Pure domain model: no adapter, no I/O. ``cairn_modules`` is a leaf consumer of
``cairn_kernel`` only (``.importlinter`` ``domain-purity`` contract), so the
actual persistence of these rows lives in
``cairn_adapters.persistence_postgres`` (migration ``0005``); this package
defines the invariants that persistence must honour and that the execution
gate (R1-22) will call before authorizing a Class C effect.
"""

from cairn_modules.approvals.model import (
    ALLOWED_APPROVAL_TRANSITIONS,
    ApprovalRecord,
    ApprovalState,
    RevisionRecord,
    bind_approval_to_revision,
    check_separation_of_duties,
    validate_approval_transition,
)

__all__ = [
    "ALLOWED_APPROVAL_TRANSITIONS",
    "ApprovalRecord",
    "ApprovalState",
    "RevisionRecord",
    "bind_approval_to_revision",
    "check_separation_of_duties",
    "validate_approval_transition",
]

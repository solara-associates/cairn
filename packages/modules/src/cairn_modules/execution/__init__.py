"""R1-21: execution state machine gated on mutation class and recovery
precondition (ADR-010).

Pure domain model, mirrored at rest by migration ``0005`` (see
``cairn_modules.approvals`` for the companion revision/approval model). R1
validates this lifecycle against a deterministic test adapter only — no
production Class C adapter exists or may be added here (ADR-010).
"""

from cairn_modules.execution.gate import ExecutionGate, ExecutionOutcome
from cairn_modules.execution.model import (
    ALLOWED_EXECUTION_TRANSITIONS,
    CompensationContract,
    ExecutionRecord,
    ExecutionState,
    RecoveryStrategy,
    authorize_execution,
    validate_execution_transition,
)

__all__ = [
    "ALLOWED_EXECUTION_TRANSITIONS",
    "CompensationContract",
    "ExecutionGate",
    "ExecutionOutcome",
    "ExecutionRecord",
    "ExecutionState",
    "RecoveryStrategy",
    "authorize_execution",
    "validate_execution_transition",
]

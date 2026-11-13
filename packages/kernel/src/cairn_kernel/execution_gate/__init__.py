"""R1-22 kernel execution-gate primitives (ADR-010).

Mutation-class-agnostic half of the gate: the adapter port, the structural
guard that rejects anything but the R1 deterministic test adapter, and
scoped idempotency (R-IDEM-01). ``cairn_modules.execution.gate`` composes
these with R1-21's approval/execution state machines to implement the full
gate lifecycle; this package has no dependency on ``cairn_modules`` (the
``.importlinter`` ``layers`` contract: kernel is a leaf).
"""

from cairn_kernel.execution_gate.deterministic_adapter import (
    FIXTURE_OPERATIONS,
    DeterministicTestExecutionAdapter,
)
from cairn_kernel.execution_gate.idempotency import (
    IdempotencyDecision,
    IdempotencyRecord,
    IdempotencyScope,
    IdempotencyStorePort,
    InMemoryIdempotencyStore,
    canonical_request_hash,
    check_idempotency,
)
from cairn_kernel.execution_gate.ports import (
    DETERMINISTIC_TEST_ADAPTER_KIND,
    AdapterRequest,
    AdapterResult,
    ExecutionAdapterPort,
    require_deterministic_test_adapter,
)

__all__ = [
    "DETERMINISTIC_TEST_ADAPTER_KIND",
    "FIXTURE_OPERATIONS",
    "AdapterRequest",
    "AdapterResult",
    "DeterministicTestExecutionAdapter",
    "ExecutionAdapterPort",
    "IdempotencyDecision",
    "IdempotencyRecord",
    "IdempotencyScope",
    "IdempotencyStorePort",
    "InMemoryIdempotencyStore",
    "canonical_request_hash",
    "check_idempotency",
    "require_deterministic_test_adapter",
]

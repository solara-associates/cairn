"""The R1 deterministic test adapter (ADR-010).

This is the only concrete ``ExecutionAdapterPort`` implementation that may
exist before R4. It is "an architecture-validation asset, not a customer
feature" (ADR-010 consequences): it makes no network call, holds no
credential of any kind, and reads no environment variable or config file —
there is nothing here for a production swap to attach to. Its output is a
pure function of its input, keyed by a small, explicit fixture table, so the
same request always produces the same result (the determinism the kernel
gate's idempotency check depends on for its replay test).

R4-02 is where a real provider adapter is built; this module is never
extended to call out anywhere, and ADR-010's release boundary ("No
production Class C adapter may exist before R4") means it never will be.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType

from cairn_kernel.errors import ProviderUnavailableError
from cairn_kernel.execution_gate.ports import (
    DETERMINISTIC_TEST_ADAPTER_KIND,
    AdapterRequest,
    AdapterResult,
)

#: Synthetic/fixture operations the adapter recognises, one per ADR-010
#: external mutation class, so R1-22's lifecycle tests can exercise the gate
#: against every class without touching a real Class C adapter.
FIXTURE_OPERATIONS: frozenset[str] = frozenset(
    {
        "fixture.rotate_api_key",  # REVERSIBLE_EXTERNAL_MUTATION
        "fixture.disable_idle_resource",  # COMPENSATABLE_EXTERNAL_MUTATION
        "fixture.purge_snapshot",  # IRREVERSIBLE_EXTERNAL_MUTATION
    }
)


class DeterministicTestExecutionAdapter:
    """``ExecutionAdapterPort`` that echoes its request back as its result.

    ``call_log`` records every call (operation + payload) in order, purely
    for tests that need to assert the adapter was, or was not, invoked —
    nothing in the adapter's own behaviour reads it back.
    """

    adapter_kind = DETERMINISTIC_TEST_ADAPTER_KIND

    def __init__(self) -> None:
        self.call_log: list[AdapterRequest] = []

    def execute(self, request: AdapterRequest) -> AdapterResult:
        if request.operation not in FIXTURE_OPERATIONS:
            raise ProviderUnavailableError(
                f"deterministic test adapter has no fixture for operation"
                f" {request.operation!r}; only {sorted(FIXTURE_OPERATIONS)} exist in R1"
            )
        self.call_log.append(request)
        detail: Mapping[str, object] = MappingProxyType(
            {"operation": request.operation, "echo": dict(request.payload)}
        )
        return AdapterResult(status="APPLIED", detail=detail)


__all__ = ["FIXTURE_OPERATIONS", "DeterministicTestExecutionAdapter"]

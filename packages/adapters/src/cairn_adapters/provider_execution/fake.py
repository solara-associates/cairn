"""787 (R4-03a) and reusable by later R4 units: a deterministic,
fully in-memory ``ProviderExecutionPort`` fake -- the "fake backend" unit
787's Terraform plan orchestration (``cairn_adapters.iac_terraform.
plan_orchestration``) is tested against. Mirrors the same "real adapter +
fake adapter" shape this codebase already uses for every other port
before a production integration is in scope
(``cairn_adapters.iac_terraform``'s ``TerraformHclGenerator``/
``FakeIaCGenerator``, ``cairn_modules.design.revisions``'s
``PostgresDesignRevisionRepository``/``FakeDesignRevisionRepository``).

Never a network call, never a cloud SDK, never a credential: ``plan``,
``apply`` and ``rollback`` are pure, deterministic, in-process functions
of their request, and every call is recorded so a test can assert exactly
what was asked of this adapter without any I/O anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cairn_kernel.hex.primitives import MutationClass

from cairn_adapters.provider_execution.ports import (
    ApplyRequest,
    ApplyResult,
    PlanRequest,
    PlanResult,
    ProviderExecutionDescriptor,
    RollbackRequest,
    RollbackResult,
)

#: Provider name and adapter kind this fake self-identifies with --
#: deliberately not a real provider name (``gcp``, ``aws``, ...) and not
#: ``DETERMINISTIC_TEST`` (the kernel execution gate's own literal for its
#: fixture adapter): this fake is a ``ProviderExecutionPort`` test double,
#: never passed to ``ExecutionGate``.
FAKE_PROVIDER = "fake"
FAKE_ADAPTER_KIND = "FAKE_PROVIDER_EXECUTION"

_SUPPORTED_MUTATION_CLASSES = frozenset(
    {
        MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
        MutationClass.COMPENSATABLE_EXTERNAL_MUTATION,
        MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
    }
)


@dataclass
class FakeProviderExecutionAdapter:
    """Records every ``plan``/``apply``/``rollback`` call it receives, in
    order, and returns a deterministic result for each -- never random,
    never time-dependent. ``plan`` echoes the request back as its preview
    (the same shape ``GcpProviderExecutionAdapter.plan`` returns for its
    skeleton), so a caller orchestrating on top of this fake can assert
    exactly what it sent."""

    next_rollback_token: str | None = "fake-rollback-token"
    plan_calls: list[PlanRequest] = field(default_factory=list)
    apply_calls: list[ApplyRequest] = field(default_factory=list)
    rollback_calls: list[RollbackRequest] = field(default_factory=list)

    @property
    def descriptor(self) -> ProviderExecutionDescriptor:
        return ProviderExecutionDescriptor(
            provider=FAKE_PROVIDER,
            adapter_kind=FAKE_ADAPTER_KIND,
            supported_mutation_classes=_SUPPORTED_MUTATION_CLASSES,
        )

    def plan(self, request: PlanRequest) -> PlanResult:
        self.plan_calls.append(request)
        return PlanResult(
            mutation_class=request.mutation_class,
            preview={"operation": request.scope.operation, "payload": dict(request.payload)},
            reversible=request.mutation_class is not MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
        )

    def apply(self, request: ApplyRequest) -> ApplyResult:
        self.apply_calls.append(request)
        return ApplyResult(
            status="APPLIED",
            detail={"operation": request.scope.operation, "payload": dict(request.payload)},
            rollback_token=self.next_rollback_token,
        )

    def rollback(self, request: RollbackRequest) -> RollbackResult:
        self.rollback_calls.append(request)
        return RollbackResult(
            status="ROLLED_BACK",
            detail={"operation": request.scope.operation, "rollback_token": request.rollback_token},
        )


__all__ = [
    "FAKE_ADAPTER_KIND",
    "FAKE_PROVIDER",
    "FakeProviderExecutionAdapter",
]

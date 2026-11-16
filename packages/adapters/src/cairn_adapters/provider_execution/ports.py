"""R4-02a: the ``ProviderExecutionPort`` contract (ADR-010, spec §5.4).

Spec §5.4's port catalogue names ``ProviderExecutionPort`` as "None before
R4; production adapters only in R4 behind ``ExecutionGatePort``" -- this
module is where that contract is defined for the first time, for the
provider adapters R4 builds behind the gate R1-22 already shipped
(``cairn_kernel.execution_gate``). It mirrors ``cairn_adapters.
provider_core.ports``'s read-only ``InventorySourcePort``/``BillingSourcePort``/
``PostureScannerPort`` shape (a provider-agnostic ``Protocol`` plus plain-data
request/result dataclasses that validate themselves), but for the write
side: plan (dry-run/preview), apply, and rollback -- one call per
ADR-009/ADR-010 recovery-relevant step, matching the three external
mutation classes (``REVERSIBLE_EXTERNAL_MUTATION``,
``COMPENSATABLE_EXTERNAL_MUTATION``, ``IRREVERSIBLE_EXTERNAL_MUTATION``)
and the compensation-contract strategies already enforced in
``cairn_modules.execution.model``.

Judgement call: ADR-010 Class C rule 8 names "rollback" and "compensation"
as the two recovery actions (plus "no rollback promise" for irreversible
mutations). This port exposes a single ``rollback`` method for both --
"compensate" is, mechanically, also an action taken after the fact against
an ``ApplyResult.rollback_token``; the semantic difference (undo vs. trigger
a separate compensating effect) lives in the compensation contract
(``cairn_kernel.classification.model.CompensationContract``) the gate
already validates before authorization, not in the adapter's call shape.
An irreversible mutation simply never produces a ``rollback_token`` an
adapter would be asked to use.

Satisfying this port alone does **not** make an adapter reachable by the
execution gate: a concrete adapter must *also* satisfy
``cairn_kernel.execution_gate.ports.ExecutionAdapterPort`` (an
``adapter_kind`` plus ``execute(AdapterRequest)``), and
``require_deterministic_test_adapter`` -- unchanged by this unit -- fails
closed against any ``adapter_kind`` other than ``DETERMINISTIC_TEST``. See
``cairn_adapters.execution_gcp.adapter`` for the first (deliberately
unreachable) production implementation of both.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from cairn_kernel.errors import ValidationError
from cairn_kernel.hex.primitives import MutationClass


@dataclass(frozen=True, slots=True)
class ProviderExecutionDescriptor:
    """Identifies a concrete ``ProviderExecutionPort`` implementation and
    what it claims to be able to execute. ``adapter_kind`` is the same
    string the kernel's ``ExecutionAdapterPort.adapter_kind`` carries --
    kept on both so a descriptor and an adapter can never silently
    disagree about which gate-guard literal the adapter self-identifies
    with."""

    provider: str
    adapter_kind: str
    supported_mutation_classes: frozenset[MutationClass]

    def __post_init__(self) -> None:
        if not self.provider.strip():
            raise ValidationError("provider execution descriptor requires a provider name")
        if not self.adapter_kind.strip():
            raise ValidationError("provider execution descriptor requires an adapter_kind")
        if not self.supported_mutation_classes:
            raise ValidationError(
                "provider execution descriptor requires at least one supported mutation class"
            )
        if MutationClass.READ_ONLY in self.supported_mutation_classes:
            raise ValidationError(
                "a provider execution adapter only ever handles external mutation classes"
            )


@dataclass(frozen=True, slots=True)
class ExecutionScope:
    """What one adapter call is scoped to. Identifiers only -- never a
    credential, never anything that outlives the call. This is the same
    tenant/project/revision binding the kernel gate and
    ``cairn_modules.execution.model`` already enforce before dispatch;
    the adapter receives it so a requested ``TokenProvider`` token can be
    scoped to the exact same revision and operation."""

    tenant_id: str
    project_id: str
    revision_id: str
    operation: str

    def __post_init__(self) -> None:
        for name, value in (
            ("tenant id", self.tenant_id),
            ("project id", self.project_id),
            ("revision id", self.revision_id),
            ("operation", self.operation),
        ):
            if not value.strip():
                raise ValidationError(f"execution scope {name} is required")


@dataclass(frozen=True, slots=True)
class PlanRequest:
    scope: ExecutionScope
    mutation_class: MutationClass
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class PlanResult:
    """A dry-run preview -- the "preflight/dry-run where supported"
    ADR-010 names for irreversible mutations, and a cheap sanity check for
    the other two classes. Never itself an effect."""

    mutation_class: MutationClass
    preview: Mapping[str, object]
    reversible: bool


@dataclass(frozen=True, slots=True)
class ApplyRequest:
    scope: ExecutionScope
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ApplyResult:
    status: str
    detail: Mapping[str, object]
    #: An opaque handle a later ``rollback`` call needs to undo this
    #: specific effect. ``None`` for an ``IRREVERSIBLE_EXTERNAL_MUTATION``,
    #: which ADR-010 says carries no rollback promise at all.
    rollback_token: str | None


@dataclass(frozen=True, slots=True)
class RollbackRequest:
    scope: ExecutionScope
    rollback_token: str
    payload: Mapping[str, object]

    def __post_init__(self) -> None:
        if not self.rollback_token.strip():
            raise ValidationError("rollback request requires a rollback_token")


@dataclass(frozen=True, slots=True)
class RollbackResult:
    status: str
    detail: Mapping[str, object]


class ProviderExecutionPort(Protocol):
    """Outbound port a production Class C execution adapter implements.

    ``plan`` is the read/dry-run step, ``apply`` is the effect, and
    ``rollback`` is the one recovery action a reversible or compensatable
    mutation's compensation contract may invoke -- all three bound to the
    same ``ExecutionScope`` (tenant, project, revision, operation) the
    gate already authorized before any of them is called.
    """

    @property
    def descriptor(self) -> ProviderExecutionDescriptor: ...

    def plan(self, request: PlanRequest) -> PlanResult: ...

    def apply(self, request: ApplyRequest) -> ApplyResult: ...

    def rollback(self, request: RollbackRequest) -> RollbackResult: ...


__all__ = [
    "ApplyRequest",
    "ApplyResult",
    "ExecutionScope",
    "PlanRequest",
    "PlanResult",
    "ProviderExecutionDescriptor",
    "ProviderExecutionPort",
    "RollbackRequest",
    "RollbackResult",
]

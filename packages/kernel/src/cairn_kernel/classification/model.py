"""R0-19 operation classification.

Entity (table/bucket) tenancy classification already exists and is already
enforced live against Postgres in ``cairn_kernel.tenancy.classification`` and
``tests/integration/test_migrations.py``; this module does not duplicate it.
It covers the other half of R0-19: the operations (APIs, MCP tools/
resources, events, worker jobs) that spec section 8.1 says carry the same
Global/Tenant/Project classification, plus Class A/B/C and mutation class.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from cairn_kernel.errors import (
    CoverageIncompleteError,
    MutationClassMismatchError,
    RecoveryPlanRequiredError,
)
from cairn_kernel.hex.primitives import OPERATION_CLASS_BY_MUTATION, MutationClass, OperationClass
from cairn_kernel.tenancy.classification import TenancyScope

EXTERNAL_MUTATION_CLASSES: frozenset[MutationClass] = frozenset(
    {
        MutationClass.REVERSIBLE_EXTERNAL_MUTATION,
        MutationClass.COMPENSATABLE_EXTERNAL_MUTATION,
        MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
    }
)


class SurfaceKind(str, Enum):
    API = "API"
    MCP_TOOL = "MCP_TOOL"
    MCP_RESOURCE = "MCP_RESOURCE"
    EVENT = "EVENT"
    WORKER_JOB = "WORKER_JOB"


class RecoveryStrategy(str, Enum):
    ROLLBACK = "ROLLBACK"
    COMPENSATE = "COMPENSATE"
    ACCEPT_IRREVERSIBLE = "ACCEPT_IRREVERSIBLE"


STRATEGY_BY_MUTATION: dict[MutationClass, RecoveryStrategy] = {
    MutationClass.REVERSIBLE_EXTERNAL_MUTATION: RecoveryStrategy.ROLLBACK,
    MutationClass.COMPENSATABLE_EXTERNAL_MUTATION: RecoveryStrategy.COMPENSATE,
    MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION: RecoveryStrategy.ACCEPT_IRREVERSIBLE,
}


@dataclass(frozen=True, slots=True)
class CompensationContract:
    """The spec section 5.3 compensation contract, bound to one external mutation."""

    strategy: RecoveryStrategy
    plan_ref: str
    preconditions: str
    authority: str
    evidence: str
    failure_handling: str

    def __post_init__(self) -> None:
        for field_name in (
            "plan_ref",
            "preconditions",
            "authority",
            "evidence",
            "failure_handling",
        ):
            if not getattr(self, field_name).strip():
                raise RecoveryPlanRequiredError(
                    f"compensation contract field {field_name!r} must not be blank"
                )


@dataclass(frozen=True, slots=True)
class OperationEntry:
    """One classified operation: an API endpoint, MCP tool/resource, event type or worker job."""

    surface: SurfaceKind
    name: str
    operation_class: OperationClass
    mutation_class: MutationClass | None
    tenancy_scope: TenancyScope
    compensation: CompensationContract | None = None
    defer_reason: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("operation name must not be blank")

        if self.mutation_class is None:
            if self.operation_class is not OperationClass.GOVERNED_ENV_MUTATION:
                raise MutationClassMismatchError(
                    f"{self.name}: only a Class C operation may defer its mutation class"
                )
            if not self.defer_reason.strip():
                raise MutationClassMismatchError(
                    f"{self.name}: a deferred mutation class needs a defer_reason"
                )
            if self.compensation is not None:
                raise MutationClassMismatchError(
                    f"{self.name}: a deferred mutation class cannot carry a compensation contract"
                )
            return

        if self.defer_reason.strip():
            raise MutationClassMismatchError(
                f"{self.name}: defer_reason is only valid when mutation_class is deferred"
            )

        expected_operation_class = OPERATION_CLASS_BY_MUTATION[self.mutation_class]
        if self.operation_class is not expected_operation_class:
            raise MutationClassMismatchError(
                f"{self.name}: {self.mutation_class.value} requires"
                f" {expected_operation_class.value}, got {self.operation_class.value}"
            )

        is_external = self.mutation_class in EXTERNAL_MUTATION_CLASSES
        if is_external and self.compensation is None:
            raise RecoveryPlanRequiredError(
                f"{self.name}: {self.mutation_class.value} requires a compensation contract"
            )
        if not is_external and self.compensation is not None:
            raise MutationClassMismatchError(
                f"{self.name}: {self.mutation_class.value} must not carry a compensation contract"
            )
        if is_external and self.compensation is not None:
            expected_strategy = STRATEGY_BY_MUTATION[self.mutation_class]
            if self.compensation.strategy is not expected_strategy:
                raise MutationClassMismatchError(
                    f"{self.name}: {self.mutation_class.value} requires strategy"
                    f" {expected_strategy.value}, got {self.compensation.strategy.value}"
                )


def operations_by_name(
    operations: tuple[OperationEntry, ...],
) -> dict[tuple[SurfaceKind, str], OperationEntry]:
    index: dict[tuple[SurfaceKind, str], OperationEntry] = {}
    for entry in operations:
        key = (entry.surface, entry.name)
        if key in index:
            raise ValueError(f"duplicate operation classification for {key}")
        index[key] = entry
    return index


def require_classified(
    index: dict[tuple[SurfaceKind, str], OperationEntry], surface: SurfaceKind, name: str
) -> None:
    if (surface, name) not in index:
        raise CoverageIncompleteError(
            f"{surface.value} {name!r} exists but has no R0-19 classification entry"
        )


__all__ = [
    "EXTERNAL_MUTATION_CLASSES",
    "STRATEGY_BY_MUTATION",
    "CompensationContract",
    "OperationEntry",
    "RecoveryStrategy",
    "SurfaceKind",
    "operations_by_name",
    "require_classified",
]

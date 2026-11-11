from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Generic, Protocol, TypeVar

from cairn_kernel.errors import MutationClassMismatchError

T = TypeVar("T")


class OperationClass(str, Enum):
    READ = "READ"                 # Class A
    WORKSPACE_MUTATION = "WORKSPACE_MUTATION"  # Class B
    GOVERNED_ENV_MUTATION = "GOVERNED_ENV_MUTATION"  # Class C


class MutationClass(str, Enum):
    READ_ONLY = "READ_ONLY"
    INTERNAL_MUTATION = "INTERNAL_MUTATION"
    REVERSIBLE_EXTERNAL_MUTATION = "REVERSIBLE_EXTERNAL_MUTATION"
    COMPENSATABLE_EXTERNAL_MUTATION = "COMPENSATABLE_EXTERNAL_MUTATION"
    IRREVERSIBLE_EXTERNAL_MUTATION = "IRREVERSIBLE_EXTERNAL_MUTATION"


class FactStatus(str, Enum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    CONFIRMED = "CONFIRMED"
    APPROXIMATE = "APPROXIMATE"
    UNAVAILABLE = "UNAVAILABLE"
    UNVERIFIED = "UNVERIFIED"


OPERATION_CLASS_BY_MUTATION: dict[MutationClass, OperationClass] = {
    MutationClass.READ_ONLY: OperationClass.READ,
    MutationClass.INTERNAL_MUTATION: OperationClass.WORKSPACE_MUTATION,
    MutationClass.REVERSIBLE_EXTERNAL_MUTATION: OperationClass.GOVERNED_ENV_MUTATION,
    MutationClass.COMPENSATABLE_EXTERNAL_MUTATION: OperationClass.GOVERNED_ENV_MUTATION,
    MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION: OperationClass.GOVERNED_ENV_MUTATION,
}


@dataclass(frozen=True, slots=True)
class TenantId:
    value: str


@dataclass(frozen=True, slots=True)
class ProjectId:
    value: str


@dataclass(frozen=True, slots=True)
class Fact(Generic[T]):
    value: T | None
    status: FactStatus
    source: str
    observed_at: datetime | None
    ingested_at: datetime
    confidence: float | None
    mapping_version: str | None
    provenance_ref: str


@dataclass(frozen=True, slots=True)
class CommandContext:
    tenant_id: TenantId
    project_id: ProjectId | None
    actor_id: str
    actor_roles: tuple[str, ...]
    correlation_id: str
    operation_class: OperationClass
    mutation_class: MutationClass
    idempotency_key: str | None = None
    source: str = "api"         # console | api | mcp | agent | job

    def __post_init__(self) -> None:
        expected = OPERATION_CLASS_BY_MUTATION[self.mutation_class]
        if self.operation_class is not expected:
            raise MutationClassMismatchError(
                f"{self.mutation_class.value} requires {expected.value},"
                f" got {self.operation_class.value}"
            )


class Port(Protocol):
    """Marker protocol for all outbound ports."""


class UnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...

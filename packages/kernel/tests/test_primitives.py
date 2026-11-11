from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from cairn_kernel.errors import ErrorCode, MutationClassMismatchError
from cairn_kernel.hex import (
    OPERATION_CLASS_BY_MUTATION,
    CommandContext,
    Fact,
    FactStatus,
    MutationClass,
    OperationClass,
    ProjectId,
    TenantId,
    UnitOfWork,
)


def make_context(
    operation_class: OperationClass,
    mutation_class: MutationClass,
) -> CommandContext:
    return CommandContext(
        tenant_id=TenantId("tenant-1"),
        project_id=ProjectId("project-1"),
        actor_id="user-1",
        actor_roles=("ARCHITECT",),
        correlation_id="corr-1",
        operation_class=operation_class,
        mutation_class=mutation_class,
    )


def test_operation_class_members() -> None:
    assert {member.value for member in OperationClass} == {
        "READ",
        "WORKSPACE_MUTATION",
        "GOVERNED_ENV_MUTATION",
    }


def test_mutation_class_members() -> None:
    assert {member.value for member in MutationClass} == {
        "READ_ONLY",
        "INTERNAL_MUTATION",
        "REVERSIBLE_EXTERNAL_MUTATION",
        "COMPENSATABLE_EXTERNAL_MUTATION",
        "IRREVERSIBLE_EXTERNAL_MUTATION",
    }


def test_every_mutation_class_has_one_operation_class() -> None:
    assert set(OPERATION_CLASS_BY_MUTATION) == set(MutationClass)


@pytest.mark.parametrize(
    "mutation_class",
    list(MutationClass),
)
def test_command_context_accepts_agreeing_classes(mutation_class: MutationClass) -> None:
    context = make_context(
        OPERATION_CLASS_BY_MUTATION[mutation_class],
        mutation_class,
    )
    assert context.mutation_class is mutation_class


@pytest.mark.parametrize(
    "mutation_class",
    list(MutationClass),
)
def test_command_context_rejects_mismatch(mutation_class: MutationClass) -> None:
    operation_class = next(
        member
        for member in OperationClass
        if member is not OPERATION_CLASS_BY_MUTATION[mutation_class]
    )
    with pytest.raises(MutationClassMismatchError) as exc_info:
        make_context(operation_class, mutation_class)
    assert exc_info.value.code is ErrorCode.MUTATION_CLASS_MISMATCH


def test_command_context_defaults() -> None:
    context = make_context(
        OperationClass.WORKSPACE_MUTATION,
        MutationClass.INTERNAL_MUTATION,
    )
    assert context.idempotency_key is None
    assert context.source == "api"


def test_tenant_id_is_immutable_value_object() -> None:
    tenant_id = TenantId("tenant-1")
    assert tenant_id == TenantId("tenant-1")
    assert hash(tenant_id) == hash(TenantId("tenant-1"))
    with pytest.raises(FrozenInstanceError):
        tenant_id.value = "tenant-2"


def test_fact_status_members() -> None:
    assert {member.value for member in FactStatus} == {
        "OBSERVED",
        "INFERRED",
        "CONFIRMED",
        "APPROXIMATE",
        "UNAVAILABLE",
        "UNVERIFIED",
    }


def test_fact_holds_typed_value_and_provenance() -> None:
    ingested_at = datetime(2026, 11, 11, tzinfo=UTC)
    fact: Fact[int] = Fact(
        value=42,
        status=FactStatus.CONFIRMED,
        source="gcp-inventory",
        observed_at=ingested_at,
        ingested_at=ingested_at,
        confidence=0.9,
        mapping_version=None,
        provenance_ref="ingest://run-1",
    )
    assert fact.value == 42
    assert fact.status is FactStatus.CONFIRMED


def test_unit_of_work_protocol_shape() -> None:
    class RecordingUnitOfWork:
        def commit(self) -> None: ...

        def rollback(self) -> None: ...

    unit_of_work: UnitOfWork = RecordingUnitOfWork()
    unit_of_work.commit()
    unit_of_work.rollback()

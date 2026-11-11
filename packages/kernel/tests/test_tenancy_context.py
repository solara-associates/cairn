from dataclasses import FrozenInstanceError

import pytest
from cairn_kernel.errors import ErrorCode, MutationClassMismatchError
from cairn_kernel.hex import CommandContext, MutationClass, OperationClass, ProjectId, TenantId
from cairn_kernel.tenancy import TenantContext


def make_context() -> TenantContext:
    return TenantContext(
        tenant_id=TenantId("tenant-1"),
        project_id=ProjectId("project-1"),
        actor_id="user-1",
        actor_roles=("ARCHITECT",),
        correlation_id="corr-1",
    )


def test_tenant_context_is_an_immutable_value() -> None:
    context = make_context()
    assert context == make_context()
    with pytest.raises(FrozenInstanceError):
        context.actor_id = "user-2"


def test_tenant_context_allows_tenant_only_scope() -> None:
    context = TenantContext(
        tenant_id=TenantId("tenant-1"),
        project_id=None,
        actor_id="user-1",
        actor_roles=("TENANT_ADMIN",),
        correlation_id="corr-1",
    )
    assert context.project_id is None


def test_to_command_context_carries_principal_and_scope() -> None:
    command_context = make_context().to_command_context(
        OperationClass.READ,
        MutationClass.READ_ONLY,
    )
    assert isinstance(command_context, CommandContext)
    assert command_context.tenant_id == TenantId("tenant-1")
    assert command_context.project_id == ProjectId("project-1")
    assert command_context.actor_id == "user-1"
    assert command_context.actor_roles == ("ARCHITECT",)
    assert command_context.correlation_id == "corr-1"
    assert command_context.idempotency_key is None
    assert command_context.source == "api"


def test_to_command_context_forwards_optional_fields() -> None:
    command_context = make_context().to_command_context(
        OperationClass.WORKSPACE_MUTATION,
        MutationClass.INTERNAL_MUTATION,
        idempotency_key="idem-1",
        source="job",
    )
    assert command_context.idempotency_key == "idem-1"
    assert command_context.source == "job"


def test_to_command_context_still_rejects_class_mismatch() -> None:
    with pytest.raises(MutationClassMismatchError) as exc_info:
        make_context().to_command_context(
            OperationClass.READ,
            MutationClass.IRREVERSIBLE_EXTERNAL_MUTATION,
        )
    assert exc_info.value.code is ErrorCode.MUTATION_CLASS_MISMATCH

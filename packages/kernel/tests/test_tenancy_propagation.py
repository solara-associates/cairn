import asyncio

import pytest
from cairn_kernel.errors import ErrorCode, TenantScopeViolationError
from cairn_kernel.hex import ProjectId, TenantId
from cairn_kernel.tenancy import (
    TenantContext,
    current_tenant_context,
    has_tenant_context,
    set_tenant_context,
    tenant_scope,
)


def make_context(
    tenant: str = "tenant-1",
    project: str | None = "project-1",
    correlation: str = "corr-1",
) -> TenantContext:
    return TenantContext(
        tenant_id=TenantId(tenant),
        project_id=ProjectId(project) if project else None,
        actor_id="user-1",
        actor_roles=("ARCHITECT",),
        correlation_id=correlation,
    )


def test_missing_context_fails_closed() -> None:
    with pytest.raises(TenantScopeViolationError) as exc_info:
        current_tenant_context()
    assert exc_info.value.code is ErrorCode.TENANT_SCOPE_VIOLATION
    assert not has_tenant_context()


def test_set_then_current_round_trips() -> None:
    context = make_context()
    with tenant_scope(context):
        assert has_tenant_context()
        assert current_tenant_context() is context


def test_scope_restores_previous_state_on_exit() -> None:
    with tenant_scope(make_context()):
        assert has_tenant_context()
    assert not has_tenant_context()
    with pytest.raises(TenantScopeViolationError):
        current_tenant_context()


def test_set_same_context_twice_is_idempotent() -> None:
    context = make_context()
    with tenant_scope(context):
        set_tenant_context(context)
        assert current_tenant_context() is context


def test_context_change_attempt_is_rejected() -> None:
    with tenant_scope(make_context(tenant="tenant-1")):
        with pytest.raises(TenantScopeViolationError) as exc_info:
            set_tenant_context(make_context(tenant="tenant-2", correlation="corr-2"))
        assert exc_info.value.code is ErrorCode.TENANT_SCOPE_VIOLATION
        assert current_tenant_context().tenant_id == TenantId("tenant-1")


def test_nested_scope_with_conflicting_tenant_is_rejected() -> None:
    with tenant_scope(make_context(tenant="tenant-1")), pytest.raises(
        TenantScopeViolationError
    ), tenant_scope(make_context(tenant="tenant-2")):
        pass


def test_nested_scope_with_same_context_is_allowed() -> None:
    context = make_context()
    with tenant_scope(context), tenant_scope(context):
        assert current_tenant_context() is context


def test_sequential_scopes_re_establish_isolation() -> None:
    with tenant_scope(make_context(tenant="tenant-1")):
        assert current_tenant_context().tenant_id == TenantId("tenant-1")
    with tenant_scope(make_context(tenant="tenant-2")):
        assert current_tenant_context().tenant_id == TenantId("tenant-2")
    assert not has_tenant_context()


def test_concurrent_scopes_do_not_leak_across_tasks() -> None:
    async def scenario(tenant: str) -> str:
        with tenant_scope(make_context(tenant=tenant, correlation=f"corr-{tenant}")):
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return current_tenant_context().tenant_id.value

    async def main() -> list[str]:
        return list(await asyncio.gather(scenario("tenant-1"), scenario("tenant-2")))

    assert asyncio.run(main()) == ["tenant-1", "tenant-2"]

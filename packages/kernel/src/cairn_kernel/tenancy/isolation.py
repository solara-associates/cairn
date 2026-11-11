from cairn_kernel.errors import TenantScopeViolationError
from cairn_kernel.hex import ProjectId, TenantId
from cairn_kernel.tenancy.context import TenantContext


def assert_tenant_allowed(context: TenantContext, tenant_id: TenantId) -> None:
    if context.tenant_id != tenant_id:
        raise TenantScopeViolationError(
            f"tenant {tenant_id.value} is outside the current tenant scope"
        )


def assert_project_allowed(context: TenantContext, project_id: ProjectId) -> None:
    if context.project_id is None:
        raise TenantScopeViolationError(
            "project access requires a project-scoped tenant context"
        )
    if context.project_id != project_id:
        raise TenantScopeViolationError(
            f"project {project_id.value} is outside the current project scope"
        )

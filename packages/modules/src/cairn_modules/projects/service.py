"""R1-01 application service: RBAC-gated use cases over a ``ProjectRepository``.

Role requirements (ADR-012, spec section 16 row R1-01):

- creating a project is a tenant-level action: ``TENANT_ADMIN`` only.
- reading a project, its membership or its settings requires any granted
  tenant role (an authenticated principal always carries at least one).
- updating a project, and managing its membership or settings, requires
  ``TENANT_ADMIN`` or ``PROJECT_OWNER``.

Tenant and cross-tenant enforcement is not duplicated here: it lives in the
repository (ADR-012), keyed off the ambient ``TenantContext`` that
``cairn_api.AuthMiddleware`` establishes per request.
"""

from __future__ import annotations

from typing import Any

from cairn_kernel.hex import ProjectId
from cairn_kernel.security import Principal, Role, require_roles

from cairn_modules.projects.domain import (
    Membership,
    Project,
    ProjectSettings,
    validate_name,
    validate_settings,
    validate_user_id,
)
from cairn_modules.projects.ports import ProjectRepository

CREATE_ROLES: tuple[Role, ...] = (Role.TENANT_ADMIN,)
MANAGE_ROLES: tuple[Role, ...] = (Role.TENANT_ADMIN, Role.PROJECT_OWNER)
READ_ROLES: tuple[Role, ...] = tuple(Role)


class ProjectService:
    def __init__(self, repository: ProjectRepository) -> None:
        self._repository = repository

    def create_project(
        self, principal: Principal, *, name: str, customer_name: str | None = None
    ) -> Project:
        require_roles(principal, *CREATE_ROLES)
        return self._repository.create_project(
            tenant_id=principal.tenant_id,
            name=validate_name(name),
            customer_name=customer_name,
        )

    def get_project(self, principal: Principal, project_id: ProjectId) -> Project:
        require_roles(principal, *READ_ROLES)
        return self._repository.get_project(project_id)

    def list_projects(self, principal: Principal) -> tuple[Project, ...]:
        require_roles(principal, *READ_ROLES)
        return self._repository.list_projects(principal.tenant_id)

    def update_project(
        self,
        principal: Principal,
        project_id: ProjectId,
        *,
        name: str | None = None,
        customer_name: str | None = None,
    ) -> Project:
        require_roles(principal, *MANAGE_ROLES)
        clean_name = validate_name(name) if name is not None else None
        return self._repository.update_project(
            project_id, name=clean_name, customer_name=customer_name
        )

    def add_member(
        self, principal: Principal, project_id: ProjectId, *, user_id: str, role: Role
    ) -> Membership:
        require_roles(principal, *MANAGE_ROLES)
        return self._repository.add_member(
            project_id,
            user_id=validate_user_id(user_id),
            role=role,
            granted_by=principal.subject,
        )

    def remove_member(self, principal: Principal, project_id: ProjectId, *, user_id: str) -> None:
        require_roles(principal, *MANAGE_ROLES)
        self._repository.remove_member(project_id, user_id=validate_user_id(user_id))

    def list_members(self, principal: Principal, project_id: ProjectId) -> tuple[Membership, ...]:
        require_roles(principal, *READ_ROLES)
        return self._repository.list_members(project_id)

    def get_settings(self, principal: Principal, project_id: ProjectId) -> ProjectSettings:
        require_roles(principal, *READ_ROLES)
        return self._repository.get_settings(project_id)

    def set_settings(
        self, principal: Principal, project_id: ProjectId, *, values: dict[str, Any]
    ) -> ProjectSettings:
        require_roles(principal, *MANAGE_ROLES)
        return self._repository.set_settings(project_id, values=validate_settings(values))


__all__ = ["CREATE_ROLES", "MANAGE_ROLES", "READ_ROLES", "ProjectService"]

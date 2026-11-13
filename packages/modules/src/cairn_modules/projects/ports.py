"""R1-01 outbound port: the storage contract for projects, membership and settings."""

from __future__ import annotations

from typing import Any, Protocol

from cairn_kernel.hex import Port, ProjectId, TenantId
from cairn_kernel.security import Role

from cairn_modules.projects.domain import Membership, Project, ProjectSettings


class ProjectRepository(Port, Protocol):
    def create_project(
        self, *, tenant_id: TenantId, name: str, customer_name: str | None
    ) -> Project: ...

    def get_project(self, project_id: ProjectId) -> Project: ...

    def list_projects(self, tenant_id: TenantId) -> tuple[Project, ...]: ...

    def update_project(
        self,
        project_id: ProjectId,
        *,
        name: str | None,
        customer_name: str | None,
    ) -> Project: ...

    def add_member(
        self, project_id: ProjectId, *, user_id: str, role: Role, granted_by: str
    ) -> Membership: ...

    def remove_member(self, project_id: ProjectId, *, user_id: str) -> None: ...

    def list_members(self, project_id: ProjectId) -> tuple[Membership, ...]: ...

    def get_settings(self, project_id: ProjectId) -> ProjectSettings: ...

    def set_settings(self, project_id: ProjectId, *, values: dict[str, Any]) -> ProjectSettings: ...


__all__ = ["ProjectRepository"]

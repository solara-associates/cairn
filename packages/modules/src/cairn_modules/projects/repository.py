"""In-memory ``ProjectRepository`` adapter.

This is the only adapter R1-01 ships: ``apps/api`` has not wired a
production datastore for any surface yet (R0 left every module a stub), so
introducing one here would be scope beyond "project, membership and
settings APIs". What this adapter does enforce, exactly like
``packages/kernel/tests/test_tenancy_isolation.py``'s ``RecordRepository``,
is tenant isolation on every read and write via the ambient
``TenantContext`` (ADR-012): a lookup for a project that belongs to another
tenant fails the same way a cross-tenant row in Postgres would under RLS,
and a lookup for a project that does not exist at all fails differently
(``NotFoundError``) so the two cases stay distinguishable in tests.
"""

from __future__ import annotations

import threading
from typing import Any

from cairn_kernel.errors import NotFoundError
from cairn_kernel.hex import IdGenerator, ProjectId, SystemClock, TenantId, UuidIdGenerator
from cairn_kernel.hex.ports import Clock
from cairn_kernel.security import Role
from cairn_kernel.tenancy import assert_tenant_allowed, current_tenant_context

from cairn_modules.projects.domain import Membership, Project, ProjectSettings


class InMemoryProjectRepository:
    """Thread-safe, process-local ``ProjectRepository``."""

    def __init__(self, *, clock: Clock | None = None, id_generator: IdGenerator | None = None) -> None:
        self._clock = clock or SystemClock()
        self._ids = id_generator or UuidIdGenerator()
        self._lock = threading.Lock()
        self._projects: dict[str, Project] = {}
        self._members: dict[str, dict[str, Membership]] = {}
        self._settings: dict[str, ProjectSettings] = {}

    def _require_project(self, project_id: ProjectId) -> Project:
        project = self._projects.get(project_id.value)
        if project is None:
            raise NotFoundError(f"project {project_id.value} does not exist")
        assert_tenant_allowed(current_tenant_context(), project.tenant_id)
        return project

    def create_project(
        self, *, tenant_id: TenantId, name: str, customer_name: str | None
    ) -> Project:
        assert_tenant_allowed(current_tenant_context(), tenant_id)
        now = self._clock.now()
        with self._lock:
            project = Project(
                project_id=ProjectId(self._ids.new_id()),
                tenant_id=tenant_id,
                name=name,
                customer_name=customer_name,
                created_at=now,
                updated_at=now,
            )
            self._projects[project.project_id.value] = project
            self._members[project.project_id.value] = {}
        return project

    def get_project(self, project_id: ProjectId) -> Project:
        return self._require_project(project_id)

    def list_projects(self, tenant_id: TenantId) -> tuple[Project, ...]:
        assert_tenant_allowed(current_tenant_context(), tenant_id)
        return tuple(
            project
            for project in self._projects.values()
            if project.tenant_id == tenant_id
        )

    def update_project(
        self,
        project_id: ProjectId,
        *,
        name: str | None,
        customer_name: str | None,
    ) -> Project:
        with self._lock:
            project = self._require_project(project_id)
            updated = Project(
                project_id=project.project_id,
                tenant_id=project.tenant_id,
                name=project.name if name is None else name,
                customer_name=project.customer_name if customer_name is None else customer_name,
                created_at=project.created_at,
                updated_at=self._clock.now(),
            )
            self._projects[project_id.value] = updated
        return updated

    def add_member(
        self, project_id: ProjectId, *, user_id: str, role: Role, granted_by: str
    ) -> Membership:
        with self._lock:
            project = self._require_project(project_id)
            membership = Membership(
                tenant_id=project.tenant_id,
                project_id=project_id,
                user_id=user_id,
                role=role,
                granted_by=granted_by,
                created_at=self._clock.now(),
            )
            self._members.setdefault(project_id.value, {})[user_id] = membership
        return membership

    def remove_member(self, project_id: ProjectId, *, user_id: str) -> None:
        with self._lock:
            self._require_project(project_id)
            members = self._members.get(project_id.value, {})
            if user_id not in members:
                raise NotFoundError(
                    f"user {user_id} is not a member of project {project_id.value}"
                )
            del members[user_id]

    def list_members(self, project_id: ProjectId) -> tuple[Membership, ...]:
        self._require_project(project_id)
        return tuple(self._members.get(project_id.value, {}).values())

    def get_settings(self, project_id: ProjectId) -> ProjectSettings:
        project = self._require_project(project_id)
        settings = self._settings.get(project_id.value)
        if settings is not None:
            return settings
        return ProjectSettings(
            tenant_id=project.tenant_id,
            project_id=project_id,
            values={},
            updated_at=project.updated_at,
        )

    def set_settings(self, project_id: ProjectId, *, values: dict[str, Any]) -> ProjectSettings:
        with self._lock:
            project = self._require_project(project_id)
            settings = ProjectSettings(
                tenant_id=project.tenant_id,
                project_id=project_id,
                values=dict(values),
                updated_at=self._clock.now(),
            )
            self._settings[project_id.value] = settings
        return settings


__all__ = ["InMemoryProjectRepository"]

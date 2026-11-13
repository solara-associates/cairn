"""R1-01: project, membership and settings HTTP routes.

RBAC and tenant isolation are not re-implemented here: every handler
delegates to ``cairn_modules.projects.ProjectService``, which enforces
roles (``cairn_kernel.security.require_roles``), and to the repository
beneath it, which enforces tenant scope off the ambient ``TenantContext``
that ``cairn_api.AuthMiddleware`` establishes per request (ADR-012). A
denial surfaces as a ``CairnError`` that the app-level exception handler
(``cairn_api.app``) turns into a Problem response.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from cairn_kernel.errors import UnauthenticatedError
from cairn_kernel.hex import ProjectId
from cairn_kernel.security import Principal, Role
from cairn_modules.projects import Membership, Project, ProjectService, ProjectSettings
from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise UnauthenticatedError("request is not authenticated")
    return principal


class CreateProjectRequest(BaseModel):
    name: str
    customer_name: str | None = None


class UpdateProjectRequest(BaseModel):
    name: str | None = None
    customer_name: str | None = None


class AddMemberRequest(BaseModel):
    user_id: str
    role: Role


class ProjectResponse(BaseModel):
    project_id: str
    tenant_id: str
    name: str
    customer_name: str | None
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_domain(cls, project: Project) -> ProjectResponse:
        return cls(
            project_id=project.project_id.value,
            tenant_id=project.tenant_id.value,
            name=project.name,
            customer_name=project.customer_name,
            created_at=project.created_at,
            updated_at=project.updated_at,
        )


class MembershipResponse(BaseModel):
    project_id: str
    user_id: str
    role: Role
    granted_by: str
    created_at: datetime

    @classmethod
    def from_domain(cls, membership: Membership) -> MembershipResponse:
        return cls(
            project_id=membership.project_id.value,
            user_id=membership.user_id,
            role=membership.role,
            granted_by=membership.granted_by,
            created_at=membership.created_at,
        )


class SettingsResponse(BaseModel):
    project_id: str
    values: dict[str, Any]
    updated_at: datetime

    @classmethod
    def from_domain(cls, settings: ProjectSettings) -> SettingsResponse:
        return cls(
            project_id=settings.project_id.value,
            values=settings.values,
            updated_at=settings.updated_at,
        )


def register_projects_routes(app: FastAPI, service: ProjectService) -> None:
    """Register the R1-01 project routes directly on ``app``.

    Routes are added to ``app`` itself rather than via ``include_router``:
    this FastAPI version resolves an included router's paths lazily (an
    opaque ``_IncludedRouter`` entry with no ``path``/``methods``), which
    ``tests/conformance/test_classification_matrix.py`` cannot see when it
    walks ``app.routes``. Registering directly keeps every route visible to
    that discovery, exactly like the existing ``/healthz``/``/readyz``
    routes in ``cairn_api.app``.
    """
    router = app

    @router.post("/v1/projects", response_model=ProjectResponse, status_code=201)
    def create_project(
        payload: CreateProjectRequest, principal: Principal = Depends(get_principal)
    ) -> ProjectResponse:
        project = service.create_project(
            principal, name=payload.name, customer_name=payload.customer_name
        )
        return ProjectResponse.from_domain(project)

    @router.get("/v1/projects", response_model=list[ProjectResponse])
    def list_projects(principal: Principal = Depends(get_principal)) -> list[ProjectResponse]:
        return [ProjectResponse.from_domain(project) for project in service.list_projects(principal)]

    @router.get("/v1/projects/{project_id}", response_model=ProjectResponse)
    def get_project(
        project_id: str, principal: Principal = Depends(get_principal)
    ) -> ProjectResponse:
        return ProjectResponse.from_domain(service.get_project(principal, ProjectId(project_id)))

    @router.patch("/v1/projects/{project_id}", response_model=ProjectResponse)
    def update_project(
        project_id: str,
        payload: UpdateProjectRequest,
        principal: Principal = Depends(get_principal),
    ) -> ProjectResponse:
        project = service.update_project(
            principal,
            ProjectId(project_id),
            name=payload.name,
            customer_name=payload.customer_name,
        )
        return ProjectResponse.from_domain(project)

    @router.get("/v1/projects/{project_id}/members", response_model=list[MembershipResponse])
    def list_members(
        project_id: str, principal: Principal = Depends(get_principal)
    ) -> list[MembershipResponse]:
        return [
            MembershipResponse.from_domain(member)
            for member in service.list_members(principal, ProjectId(project_id))
        ]

    @router.post(
        "/v1/projects/{project_id}/members", response_model=MembershipResponse, status_code=201
    )
    def add_member(
        project_id: str,
        payload: AddMemberRequest,
        principal: Principal = Depends(get_principal),
    ) -> MembershipResponse:
        membership = service.add_member(
            principal, ProjectId(project_id), user_id=payload.user_id, role=payload.role
        )
        return MembershipResponse.from_domain(membership)

    @router.delete(
        "/v1/projects/{project_id}/members/{user_id}", status_code=204, response_model=None
    )
    def remove_member(
        project_id: str, user_id: str, principal: Principal = Depends(get_principal)
    ) -> Response:
        service.remove_member(principal, ProjectId(project_id), user_id=user_id)
        return Response(status_code=204)

    @router.get("/v1/projects/{project_id}/settings", response_model=SettingsResponse)
    def get_settings(
        project_id: str, principal: Principal = Depends(get_principal)
    ) -> SettingsResponse:
        return SettingsResponse.from_domain(service.get_settings(principal, ProjectId(project_id)))

    @router.put("/v1/projects/{project_id}/settings", response_model=SettingsResponse)
    def set_settings(
        project_id: str,
        payload: dict[str, Any],
        principal: Principal = Depends(get_principal),
    ) -> SettingsResponse:
        settings = service.set_settings(principal, ProjectId(project_id), values=payload)
        return SettingsResponse.from_domain(settings)


__all__ = ["get_principal", "register_projects_routes"]

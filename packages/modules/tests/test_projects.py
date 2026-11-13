"""R1-01: project, membership and settings APIs — domain/service layer.

Pure in-process tests, no database: cross-tenant isolation is proven the
same way ``packages/kernel/tests/test_tenancy_isolation.py`` proves it for
a generic repository, via the ambient ``TenantContext`` (ADR-012). The HTTP
layer is covered separately in ``apps/api/tests/test_projects_api.py``.
"""

from __future__ import annotations

import pytest
from cairn_kernel.errors import (
    ForbiddenError,
    NotFoundError,
    TenantScopeViolationError,
    ValidationError,
)
from cairn_kernel.hex import ProjectId, TenantId
from cairn_kernel.security import Principal, Role
from cairn_kernel.tenancy import TenantContext, tenant_scope
from cairn_modules.projects import InMemoryProjectRepository, ProjectService

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "22222222-2222-2222-2222-222222222222"


def _principal(tenant: str, *roles: Role, subject: str = "user-1") -> Principal:
    return Principal(subject=subject, tenant_id=TenantId(tenant), roles=roles)


def _context(tenant: str, *roles: str, actor: str = "user-1") -> TenantContext:
    return TenantContext(
        tenant_id=TenantId(tenant),
        project_id=None,
        actor_id=actor,
        actor_roles=roles,
        correlation_id="corr-1",
    )


def _service() -> ProjectService:
    return ProjectService(InMemoryProjectRepository())


# --- create: happy path, RBAC denial, validation ---------------------------


def test_tenant_admin_can_create_a_project() -> None:
    service = _service()
    admin = _principal(TENANT_A, Role.TENANT_ADMIN)
    with tenant_scope(_context(TENANT_A, "TENANT_ADMIN")):
        project = service.create_project(admin, name="Migration Alpha")
    assert project.name == "Migration Alpha"
    assert project.tenant_id == TenantId(TENANT_A)


def test_non_admin_cannot_create_a_project() -> None:
    service = _service()
    viewer = _principal(TENANT_A, Role.VIEWER)
    with tenant_scope(_context(TENANT_A, "VIEWER")), pytest.raises(ForbiddenError):
        service.create_project(viewer, name="Migration Alpha")


def test_create_project_rejects_a_blank_name() -> None:
    service = _service()
    admin = _principal(TENANT_A, Role.TENANT_ADMIN)
    with tenant_scope(_context(TENANT_A, "TENANT_ADMIN")), pytest.raises(ValidationError):
        service.create_project(admin, name="   ")


def test_create_project_rejects_an_overlong_name() -> None:
    service = _service()
    admin = _principal(TENANT_A, Role.TENANT_ADMIN)
    with tenant_scope(_context(TENANT_A, "TENANT_ADMIN")), pytest.raises(ValidationError):
        service.create_project(admin, name="x" * 201)


# --- read / update -----------------------------------------------------------


def _created_project(service: ProjectService):
    admin = _principal(TENANT_A, Role.TENANT_ADMIN)
    with tenant_scope(_context(TENANT_A, "TENANT_ADMIN")):
        return service.create_project(admin, name="Migration Alpha", customer_name="Acme")


def test_any_granted_role_can_read_a_project() -> None:
    service = _service()
    project = _created_project(service)
    viewer = _principal(TENANT_A, Role.VIEWER)
    with tenant_scope(_context(TENANT_A, "VIEWER")):
        fetched = service.get_project(viewer, project.project_id)
    assert fetched == project


def test_reading_an_unknown_project_is_not_found() -> None:
    service = _service()
    viewer = _principal(TENANT_A, Role.VIEWER)
    with tenant_scope(_context(TENANT_A, "VIEWER")), pytest.raises(NotFoundError):
        service.get_project(viewer, ProjectId("does-not-exist"))


def test_project_owner_can_update_a_project() -> None:
    service = _service()
    project = _created_project(service)
    owner = _principal(TENANT_A, Role.PROJECT_OWNER)
    with tenant_scope(_context(TENANT_A, "PROJECT_OWNER")):
        updated = service.update_project(owner, project.project_id, name="Migration Beta")
    assert updated.name == "Migration Beta"
    assert updated.customer_name == "Acme"


def test_viewer_cannot_update_a_project() -> None:
    service = _service()
    project = _created_project(service)
    viewer = _principal(TENANT_A, Role.VIEWER)
    with tenant_scope(_context(TENANT_A, "VIEWER")), pytest.raises(ForbiddenError):
        service.update_project(viewer, project.project_id, name="Migration Beta")


def test_list_projects_is_scoped_to_the_caller_tenant() -> None:
    service = _service()
    admin_a = _principal(TENANT_A, Role.TENANT_ADMIN)
    admin_b = _principal(TENANT_B, Role.TENANT_ADMIN)
    with tenant_scope(_context(TENANT_A, "TENANT_ADMIN")):
        service.create_project(admin_a, name="Alpha")
    with tenant_scope(_context(TENANT_B, "TENANT_ADMIN")):
        service.create_project(admin_b, name="Beta")
    with tenant_scope(_context(TENANT_A, "TENANT_ADMIN")):
        names = {project.name for project in service.list_projects(admin_a)}
    assert names == {"Alpha"}


# --- cross-tenant adversarial tests -----------------------------------------


def test_cross_tenant_read_is_denied() -> None:
    service = _service()
    project = _created_project(service)
    intruder = _principal(TENANT_B, Role.TENANT_ADMIN)
    with tenant_scope(_context(TENANT_B, "TENANT_ADMIN")), pytest.raises(TenantScopeViolationError):
        service.get_project(intruder, project.project_id)


def test_cross_tenant_update_is_denied() -> None:
    service = _service()
    project = _created_project(service)
    intruder = _principal(TENANT_B, Role.TENANT_ADMIN)
    with tenant_scope(_context(TENANT_B, "TENANT_ADMIN")), pytest.raises(TenantScopeViolationError):
        service.update_project(intruder, project.project_id, name="Hijacked")


def test_cross_tenant_settings_read_is_denied() -> None:
    service = _service()
    project = _created_project(service)
    intruder = _principal(TENANT_B, Role.TENANT_ADMIN)
    with tenant_scope(_context(TENANT_B, "TENANT_ADMIN")), pytest.raises(TenantScopeViolationError):
        service.get_settings(intruder, project.project_id)


def test_cross_tenant_member_add_is_denied() -> None:
    service = _service()
    project = _created_project(service)
    intruder = _principal(TENANT_B, Role.TENANT_ADMIN)
    with tenant_scope(_context(TENANT_B, "TENANT_ADMIN")), pytest.raises(TenantScopeViolationError):
        service.add_member(intruder, project.project_id, user_id="victim", role=Role.VIEWER)


def test_cross_tenant_member_list_is_denied() -> None:
    service = _service()
    project = _created_project(service)
    intruder = _principal(TENANT_B, Role.VIEWER)
    with tenant_scope(_context(TENANT_B, "VIEWER")), pytest.raises(TenantScopeViolationError):
        service.list_members(intruder, project.project_id)


# --- membership ---------------------------------------------------------------


def test_project_owner_can_add_and_list_members() -> None:
    service = _service()
    project = _created_project(service)
    owner = _principal(TENANT_A, Role.PROJECT_OWNER)
    with tenant_scope(_context(TENANT_A, "PROJECT_OWNER")):
        service.add_member(owner, project.project_id, user_id="alice", role=Role.ENGINEER)
        members = service.list_members(owner, project.project_id)
    assert {member.user_id for member in members} == {"alice"}
    assert members[0].role is Role.ENGINEER
    assert members[0].granted_by == owner.subject


def test_viewer_cannot_add_a_member() -> None:
    service = _service()
    project = _created_project(service)
    viewer = _principal(TENANT_A, Role.VIEWER)
    with tenant_scope(_context(TENANT_A, "VIEWER")), pytest.raises(ForbiddenError):
        service.add_member(viewer, project.project_id, user_id="alice", role=Role.ENGINEER)


def test_add_member_rejects_a_blank_user_id() -> None:
    service = _service()
    project = _created_project(service)
    owner = _principal(TENANT_A, Role.PROJECT_OWNER)
    with tenant_scope(_context(TENANT_A, "PROJECT_OWNER")), pytest.raises(ValidationError):
        service.add_member(owner, project.project_id, user_id="  ", role=Role.ENGINEER)


def test_project_owner_can_remove_a_member() -> None:
    service = _service()
    project = _created_project(service)
    owner = _principal(TENANT_A, Role.PROJECT_OWNER)
    with tenant_scope(_context(TENANT_A, "PROJECT_OWNER")):
        service.add_member(owner, project.project_id, user_id="alice", role=Role.ENGINEER)
        service.remove_member(owner, project.project_id, user_id="alice")
        members = service.list_members(owner, project.project_id)
    assert members == ()


def test_removing_an_unknown_member_is_not_found() -> None:
    service = _service()
    project = _created_project(service)
    owner = _principal(TENANT_A, Role.PROJECT_OWNER)
    with tenant_scope(_context(TENANT_A, "PROJECT_OWNER")), pytest.raises(NotFoundError):
        service.remove_member(owner, project.project_id, user_id="ghost")


# --- settings ------------------------------------------------------------------


def test_default_settings_are_empty() -> None:
    service = _service()
    project = _created_project(service)
    viewer = _principal(TENANT_A, Role.VIEWER)
    with tenant_scope(_context(TENANT_A, "VIEWER")):
        settings = service.get_settings(viewer, project.project_id)
    assert settings.values == {}


def test_project_owner_can_set_and_read_settings() -> None:
    service = _service()
    project = _created_project(service)
    owner = _principal(TENANT_A, Role.PROJECT_OWNER)
    with tenant_scope(_context(TENANT_A, "PROJECT_OWNER")):
        service.set_settings(owner, project.project_id, values={"notify": True, "region": "us"})
        settings = service.get_settings(owner, project.project_id)
    assert settings.values == {"notify": True, "region": "us"}


def test_viewer_cannot_set_settings() -> None:
    service = _service()
    project = _created_project(service)
    viewer = _principal(TENANT_A, Role.VIEWER)
    with tenant_scope(_context(TENANT_A, "VIEWER")), pytest.raises(ForbiddenError):
        service.set_settings(viewer, project.project_id, values={"notify": True})


def test_set_settings_rejects_a_non_object_payload() -> None:
    service = _service()
    project = _created_project(service)
    owner = _principal(TENANT_A, Role.PROJECT_OWNER)
    with tenant_scope(_context(TENANT_A, "PROJECT_OWNER")), pytest.raises(ValidationError):
        service.set_settings(owner, project.project_id, values=["not", "a", "dict"])  # type: ignore[arg-type]


def test_set_settings_rejects_non_json_serializable_values() -> None:
    service = _service()
    project = _created_project(service)
    owner = _principal(TENANT_A, Role.PROJECT_OWNER)
    with tenant_scope(_context(TENANT_A, "PROJECT_OWNER")), pytest.raises(ValidationError):
        service.set_settings(owner, project.project_id, values={"bad": object()})

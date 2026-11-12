import pytest
from cairn_kernel.errors import ForbiddenError
from cairn_kernel.hex import TenantId
from cairn_kernel.security import (
    TENANT_ROLES,
    Principal,
    Role,
    require_roles,
    role_from_claim,
)

TENANT = TenantId("6f0f0f31-6d0c-4f25-9a45-1d0e1a0f1f6a")


def _principal(*roles: Role) -> Principal:
    return Principal(subject="user-1", tenant_id=TENANT, roles=roles)


def test_every_spec_role_is_declared() -> None:
    assert TENANT_ROLES == {
        "TENANT_ADMIN",
        "PROJECT_OWNER",
        "ARCHITECT",
        "ENGINEER",
        "REVIEWER",
        "AUDITOR",
        "VIEWER",
    }


def test_principal_reports_roles() -> None:
    principal = _principal(Role.ARCHITECT, Role.VIEWER)
    assert principal.has_role(Role.ARCHITECT)
    assert not principal.has_role(Role.TENANT_ADMIN)
    assert principal.role_values() == ("ARCHITECT", "VIEWER")


def test_require_roles_allows_any_held_role() -> None:
    require_roles(_principal(Role.ENGINEER), Role.ENGINEER, Role.ARCHITECT)


def test_require_roles_rejects_missing_roles() -> None:
    with pytest.raises(ForbiddenError, match="ENGINEER, ARCHITECT"):
        require_roles(_principal(Role.VIEWER), Role.ENGINEER, Role.ARCHITECT)


def test_require_roles_needs_a_role() -> None:
    with pytest.raises(ValueError, match="at least one role"):
        require_roles(_principal(Role.VIEWER))


def test_role_from_claim_maps_known_roles_only() -> None:
    assert role_from_claim("AUDITOR") is Role.AUDITOR
    assert role_from_claim("PLATFORM_OPERATOR") is None
    assert role_from_claim("viewer") is None

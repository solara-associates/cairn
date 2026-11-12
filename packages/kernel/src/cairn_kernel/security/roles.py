from enum import Enum


class Role(str, Enum):
    TENANT_ADMIN = "TENANT_ADMIN"
    PROJECT_OWNER = "PROJECT_OWNER"
    ARCHITECT = "ARCHITECT"
    ENGINEER = "ENGINEER"
    REVIEWER = "REVIEWER"
    AUDITOR = "AUDITOR"
    VIEWER = "VIEWER"


TENANT_ROLES = frozenset(role.value for role in Role)


def role_from_claim(value: str) -> Role | None:
    try:
        return Role(value)
    except ValueError:
        return None

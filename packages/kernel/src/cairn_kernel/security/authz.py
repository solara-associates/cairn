from cairn_kernel.errors import ForbiddenError
from cairn_kernel.security.principal import Principal
from cairn_kernel.security.roles import Role


def require_roles(principal: Principal, *allowed: Role) -> None:
    if not allowed:
        raise ValueError("require_roles needs at least one role")
    if not any(principal.has_role(role) for role in allowed):
        required = ", ".join(role.value for role in allowed)
        raise ForbiddenError(f"principal lacks a required role: {required}")

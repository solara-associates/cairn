from dataclasses import dataclass

from cairn_kernel.hex import TenantId
from cairn_kernel.security.roles import Role


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    tenant_id: TenantId
    roles: tuple[Role, ...]
    email: str | None = None

    def has_role(self, role: Role) -> bool:
        return role in self.roles

    def role_values(self) -> tuple[str, ...]:
        return tuple(role.value for role in self.roles)

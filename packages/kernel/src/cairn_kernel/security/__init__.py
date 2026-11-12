"""CAIRN cairn_kernel.security."""

from cairn_kernel.security.assertion import (
    sign_tenant_assertion,
    tenant_assertion_payload,
)
from cairn_kernel.security.audit import AuditEntry, AuditSink
from cairn_kernel.security.authz import require_roles
from cairn_kernel.security.principal import Principal
from cairn_kernel.security.roles import TENANT_ROLES, Role, role_from_claim

__all__ = [
    "TENANT_ROLES",
    "AuditEntry",
    "AuditSink",
    "Principal",
    "Role",
    "require_roles",
    "role_from_claim",
    "sign_tenant_assertion",
    "tenant_assertion_payload",
]

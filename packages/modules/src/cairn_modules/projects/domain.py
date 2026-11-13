"""R1-01 domain model: projects, project membership and project settings.

Tenant isolation follows ADR-012 (RLS, composite keys): every entity here
carries its owning ``tenant_id`` and is looked up through
``cairn_kernel.tenancy`` so a cross-tenant read or write fails the same way
``packages/kernel/tests/test_tenancy_isolation.py`` already proves for a
generic repository.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cairn_kernel.errors import ValidationError
from cairn_kernel.hex import ProjectId, TenantId
from cairn_kernel.security import Role

MAX_NAME_LENGTH = 200


@dataclass(frozen=True, slots=True)
class Project:
    project_id: ProjectId
    tenant_id: TenantId
    name: str
    customer_name: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class Membership:
    tenant_id: TenantId
    project_id: ProjectId
    user_id: str
    role: Role
    granted_by: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ProjectSettings:
    tenant_id: TenantId
    project_id: ProjectId
    values: dict[str, Any]
    updated_at: datetime


def validate_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise ValidationError("project name must not be blank")
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ValidationError(f"project name must be at most {MAX_NAME_LENGTH} characters")
    return cleaned


def validate_user_id(user_id: str) -> str:
    cleaned = user_id.strip()
    if not cleaned:
        raise ValidationError("user_id must not be blank")
    return cleaned


def validate_settings(values: Any) -> dict[str, Any]:
    if not isinstance(values, dict):
        raise ValidationError("settings must be a JSON object")
    for key in values:
        if not isinstance(key, str):
            raise ValidationError("settings keys must be strings")
    try:
        json.dumps(values)
    except (TypeError, ValueError) as exc:
        raise ValidationError("settings must be JSON-serializable") from exc
    return values


__all__ = [
    "MAX_NAME_LENGTH",
    "Membership",
    "Project",
    "ProjectSettings",
    "validate_name",
    "validate_settings",
    "validate_user_id",
]

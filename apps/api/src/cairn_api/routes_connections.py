"""R1-02: provider connection create/validate/revoke HTTP routes.

Delegates entirely to ``cairn_modules.connections.ConnectionRegistry``,
which already enforces ADR-010 (read-only scope only, no execution
credential) and ADR-008 (revoke is audit-before-effect). This module
adds nothing beyond HTTP plumbing and the same ambient-tenant-context
check ``routes_assessment.py`` uses: a connection belonging to another
tenant or a different project than named in the path is reported as
NotFound, never as Forbidden, so its existence is never leaked.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from cairn_kernel.errors import NotFoundError, UnauthenticatedError
from cairn_kernel.security import Principal
from cairn_modules.connections import (
    ConnectionRegistry,
    ConnectionScope,
    ConnectionStatus,
    ConnectionSummary,
    ProviderScopeValidator,
    ScopeCheckResult,
)
from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel


def get_principal(request: Request) -> Principal:
    principal = getattr(request.state, "principal", None)
    if principal is None:
        raise UnauthenticatedError("request is not authenticated")
    return principal


class _AlwaysReadOnlyValidator(ProviderScopeValidator):
    """Default console-wiring validator.

    No real GCP round-trip exists in this codebase yet (R0-13's
    ``FakeProviderAdapter`` is a test double, not something apps/api
    wires in); ``ConnectionRegistry.create`` already rejects anything
    but ``READ_ONLY`` scope outright (ADR-010), so a validator that
    reports every connection as read-only and reachable adds no risk
    here -- it documents the honest absence of a live check, the same
    way R0-13's fake adapter stands in elsewhere before a real one
    exists.
    """

    def check_scope(
        self, *, provider: str, account_id: str, credential_ref: str
    ) -> ScopeCheckResult:
        return ScopeCheckResult(
            read_only=True, reachable=True, detail="no live provider check wired yet"
        )


class CreateConnectionRequest(BaseModel):
    provider: str
    account_id: str
    secret: str


class ConnectionResponse(BaseModel):
    connection_id: str
    tenant_id: str
    project_id: str
    provider: str
    account_id: str
    scope: ConnectionScope
    status: ConnectionStatus
    created_at: datetime
    last_validated_at: datetime | None
    revoked_at: datetime | None

    @classmethod
    def from_domain(cls, summary: ConnectionSummary) -> ConnectionResponse:
        return cls(
            connection_id=summary.connection_id,
            tenant_id=summary.tenant_id,
            project_id=summary.project_id,
            provider=summary.provider,
            account_id=summary.account_id,
            scope=summary.scope,
            status=summary.status,
            created_at=summary.created_at,
            last_validated_at=summary.last_validated_at,
            revoked_at=summary.revoked_at,
        )


def _require_same_tenant_and_project(
    summary: ConnectionSummary, *, project_id: str, principal: Principal
) -> None:
    if summary.tenant_id != principal.tenant_id.value or summary.project_id != project_id:
        raise NotFoundError(f"provider connection {summary.connection_id} not found")


def register_connections_routes(
    app: FastAPI,
    *,
    registry: ConnectionRegistry,
    validator: ProviderScopeValidator | None = None,
) -> None:
    """Register the R1-02 provider-connection routes directly on ``app``.

    Directly on ``app``, not via ``include_router`` -- see
    ``cairn_api.routes_projects.register_projects_routes`` for why.
    """
    router = app
    scope_validator = validator or _AlwaysReadOnlyValidator()

    @router.post(
        "/v1/projects/{project_id}/connections",
        response_model=ConnectionResponse,
        status_code=201,
    )
    def create_connection(
        project_id: str,
        payload: CreateConnectionRequest,
        principal: Principal = Depends(get_principal),
    ) -> ConnectionResponse:
        connection_id = str(uuid.uuid4())
        summary = registry.create(
            connection_id=connection_id,
            tenant_id=principal.tenant_id.value,
            project_id=project_id,
            provider=payload.provider,
            account_id=payload.account_id,
            secret=payload.secret,
            actor_id=principal.subject,
        )
        return ConnectionResponse.from_domain(summary)

    @router.get(
        "/v1/projects/{project_id}/connections/{connection_id}",
        response_model=ConnectionResponse,
    )
    def get_connection(
        project_id: str, connection_id: str, principal: Principal = Depends(get_principal)
    ) -> ConnectionResponse:
        summary = registry.get(connection_id)
        _require_same_tenant_and_project(summary, project_id=project_id, principal=principal)
        return ConnectionResponse.from_domain(summary)

    @router.post(
        "/v1/projects/{project_id}/connections/{connection_id}/validate",
        response_model=ConnectionResponse,
    )
    def validate_connection(
        project_id: str, connection_id: str, principal: Principal = Depends(get_principal)
    ) -> ConnectionResponse:
        existing = registry.get(connection_id)
        _require_same_tenant_and_project(existing, project_id=project_id, principal=principal)
        summary = registry.validate(connection_id, validator=scope_validator)
        return ConnectionResponse.from_domain(summary)

    @router.post(
        "/v1/projects/{project_id}/connections/{connection_id}/revoke",
        response_model=ConnectionResponse,
    )
    def revoke_connection(
        project_id: str, connection_id: str, principal: Principal = Depends(get_principal)
    ) -> ConnectionResponse:
        existing = registry.get(connection_id)
        _require_same_tenant_and_project(existing, project_id=project_id, principal=principal)
        summary = registry.revoke(connection_id, actor_id=principal.subject)
        return ConnectionResponse.from_domain(summary)


__all__ = ["get_principal", "register_connections_routes"]

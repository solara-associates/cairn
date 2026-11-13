"""R1-02: provider connection create/validate/revoke lifecycle, for GCP.

ADR-010: a provider connection in R1 only ever carries a read-only
assessment credential. No execution credential, no write/execute scope, and
no Class C path exists here or anywhere before R4 -- this module manages a
connection record, it never executes anything.

ADR-008: revoke is audit-before-effect. The audit entry is appended before
the connection is marked revoked; if the audit sink is unavailable, revoke
fails closed and the connection stays ACTIVE.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from cairn_kernel.errors import (
    ForbiddenError,
    NotFoundError,
    ProviderUnavailableError,
    ValidationError,
)
from cairn_kernel.hex import OperationClass, ProjectId, TenantId
from cairn_kernel.security import AuditEntry, AuditSink

from cairn_modules.connections.models import (
    ConnectionScope,
    ConnectionStatus,
    ConnectionSummary,
    ProviderConnectionRecord,
)
from cairn_modules.connections.ports import ProviderScopeValidator
from cairn_modules.connections.secrets import digest_secret

ACTION_REVOKE = "provider_connection.revoke"


class ConnectionRegistry:
    """In-memory R1-02 connection lifecycle: create, validate, revoke."""

    def __init__(
        self,
        *,
        audit_sink: AuditSink,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._records: dict[str, ProviderConnectionRecord] = {}
        self._audit_sink = audit_sink
        self._clock = clock or (lambda: datetime.now(UTC))

    def create(
        self,
        *,
        connection_id: str,
        tenant_id: str,
        project_id: str,
        provider: str,
        account_id: str,
        secret: str,
        actor_id: str,
        scope: ConnectionScope = ConnectionScope.READ_ONLY,
    ) -> ConnectionSummary:
        for field_name, value in (
            ("connection id", connection_id),
            ("tenant id", tenant_id),
            ("project id", project_id),
            ("provider", provider),
            ("account id", account_id),
            ("actor id", actor_id),
        ):
            if not value.strip():
                raise ValidationError(f"provider connection {field_name} is required")
        if scope is not ConnectionScope.READ_ONLY:
            raise ForbiddenError(
                f"provider connection scope {scope.value} is not permitted before R4"
                " (ADR-010); only READ_ONLY connections may be created"
            )
        if connection_id in self._records:
            raise ValidationError(f"provider connection {connection_id} already exists")

        digest = digest_secret(secret)
        record = ProviderConnectionRecord(
            connection_id=connection_id,
            tenant_id=tenant_id,
            project_id=project_id,
            provider=provider,
            account_id=account_id,
            scope=scope,
            secret_digest=digest,
            status=ConnectionStatus.ACTIVE,
            created_at=self._clock(),
        )
        self._records[connection_id] = record
        return record.to_summary()

    def get(self, connection_id: str) -> ConnectionSummary:
        return self._require(connection_id).to_summary()

    def validate(
        self,
        connection_id: str,
        *,
        validator: ProviderScopeValidator,
    ) -> ConnectionSummary:
        record = self._require(connection_id)
        if record.status is ConnectionStatus.REVOKED:
            raise ValidationError(f"provider connection {connection_id} is revoked")

        result = validator.check_scope(
            provider=record.provider,
            account_id=record.account_id,
            credential_ref=record.secret_digest.digest_hex,
        )
        if not result.read_only:
            raise ForbiddenError(
                f"provider connection {connection_id} validation reported a"
                " non-read-only scope; rejected (ADR-010, no execution scope before R4)"
            )
        if not result.reachable:
            raise ProviderUnavailableError(
                f"provider connection {connection_id} failed its read-only round-trip check"
                f"{': ' + result.detail if result.detail else ''}"
            )

        updated = replace(record, last_validated_at=self._clock())
        self._records[connection_id] = updated
        return updated.to_summary()

    def revoke(self, connection_id: str, *, actor_id: str) -> ConnectionSummary:
        if not actor_id.strip():
            raise ValidationError("actor id is required to revoke a provider connection")
        record = self._require(connection_id)
        if record.status is ConnectionStatus.REVOKED:
            # Idempotent: revoking an already-revoked connection re-emits no
            # audit entry and returns the existing state.
            return record.to_summary()

        entry = AuditEntry(
            tenant_id=TenantId(record.tenant_id),
            project_id=ProjectId(record.project_id),
            actor=actor_id,
            action=ACTION_REVOKE,
            operation_class=OperationClass.WORKSPACE_MUTATION,
            payload={
                "connection_id": record.connection_id,
                "provider": record.provider,
                "account_id": record.account_id,
            },
        )
        # ADR-008 audit-before-effect: appended before the record below is
        # mutated. A raised AuditUnavailableError propagates and the
        # connection is left ACTIVE -- revoke fails closed.
        audit_id = self._audit_sink.append(entry)

        updated = replace(
            record,
            status=ConnectionStatus.REVOKED,
            revoked_at=self._clock(),
            revocation_audit_id=audit_id,
        )
        self._records[connection_id] = updated
        return updated.to_summary()

    def _require(self, connection_id: str) -> ProviderConnectionRecord:
        try:
            return self._records[connection_id]
        except KeyError as exc:
            raise NotFoundError(f"provider connection {connection_id} is not known") from exc


__all__ = ["ConnectionRegistry"]

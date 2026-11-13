"""Domain model for R1-02: GCP provider connections.

ADR-010 confines CAIRN to read-only assessment credentials before R4; a
provider connection record in R1 never carries execution credentials or a
write/execute scope. The raw secret is never retained anywhere in this
module -- only a one-way digest (``SecretDigest``) is stored, and every
externally visible shape (``ConnectionSummary``) carries no secret material
at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ConnectionScope(str, Enum):
    """The scope requested for a provider connection.

    Only READ_ONLY may ever be created or validated successfully (ADR-010);
    WRITE and EXECUTE exist so a request carrying one can be classified and
    rejected explicitly, rather than silently coerced to read-only.
    """

    READ_ONLY = "READ_ONLY"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"


class ConnectionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


@dataclass(frozen=True, slots=True)
class SecretDigest:
    """A one-way digest of a provider credential.

    The original secret cannot be recovered from this; ``digest_hex`` is a
    salted SHA-256 hash and ``salt_hex`` is the per-connection salt used to
    compute it.
    """

    algorithm: str
    salt_hex: str
    digest_hex: str


@dataclass(frozen=True, slots=True)
class ConnectionSummary:
    """The only shape a provider connection is ever returned in.

    Carries no secret material, directly or indirectly -- not even the
    digest, which is internal bookkeeping only.
    """

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


@dataclass(frozen=True, slots=True)
class ProviderConnectionRecord:
    """The internal connection record. Never serialize this directly outward;
    use ``to_summary()``."""

    connection_id: str
    tenant_id: str
    project_id: str
    provider: str
    account_id: str
    scope: ConnectionScope
    secret_digest: SecretDigest
    status: ConnectionStatus
    created_at: datetime
    last_validated_at: datetime | None = None
    revoked_at: datetime | None = None
    revocation_audit_id: str | None = None

    def to_summary(self) -> ConnectionSummary:
        return ConnectionSummary(
            connection_id=self.connection_id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            provider=self.provider,
            account_id=self.account_id,
            scope=self.scope,
            status=self.status,
            created_at=self.created_at,
            last_validated_at=self.last_validated_at,
            revoked_at=self.revoked_at,
        )


__all__ = [
    "ConnectionScope",
    "ConnectionStatus",
    "ConnectionSummary",
    "ProviderConnectionRecord",
    "SecretDigest",
]

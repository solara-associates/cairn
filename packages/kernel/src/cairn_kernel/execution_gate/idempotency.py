"""Scoped idempotency for Class B/C mutations (R-IDEM-01).

Generic, mutation-class-agnostic mechanism: tenant/project/operation/key
scope, canonical request hashing, replay/conflict handling and expiry. The
execution gate (``cairn_modules.execution.gate``) uses this for every Class C
dispatch; nothing here depends on the approval/execution state machines, so
a future Class B call site can reuse it without this package growing a
reverse dependency on ``cairn_modules``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from cairn_kernel.errors import IdempotencyConflictError
from cairn_kernel.hex.primitives import ProjectId, TenantId
from cairn_kernel.security.canonical import canonical_json, freeze_json


@dataclass(frozen=True, slots=True)
class IdempotencyScope:
    """R-IDEM-01: idempotency is scoped to tenant, project, operation and the
    caller-supplied key — the same key reused for a different operation, or
    by a different tenant/project, is a different scope entirely."""

    tenant_id: TenantId
    project_id: ProjectId | None
    operation: str
    key: str

    def __post_init__(self) -> None:
        if not self.operation.strip():
            raise ValueError("operation must not be blank")
        if not self.key.strip():
            raise ValueError("idempotency key must not be blank")


@dataclass(frozen=True, slots=True)
class IdempotencyRecord:
    scope: IdempotencyScope
    request_hash: str
    result: Mapping[str, object]
    created_at: datetime
    expires_at: datetime


def canonical_request_hash(payload: Mapping[str, object]) -> str:
    """Hash the canonical JSON form of ``payload`` so a retry that differs
    only in key order or container type still resolves to the same request
    identity (the same discipline ``cairn_kernel.security.audit.entry_hash``
    uses for the audit chain)."""

    canonical = canonical_json(freeze_json(dict(payload)))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class IdempotencyStorePort(Protocol):
    def get(self, scope: IdempotencyScope) -> IdempotencyRecord | None: ...

    def put(self, record: IdempotencyRecord) -> None: ...


class InMemoryIdempotencyStore:
    """Deterministic ``IdempotencyStorePort`` for the R1 gate harness and its
    tests. A durable store is an adapter-layer concern for whichever release
    first needs cross-process idempotency; nothing about this port requires
    one before then."""

    def __init__(self) -> None:
        self._records: dict[IdempotencyScope, IdempotencyRecord] = {}

    def get(self, scope: IdempotencyScope) -> IdempotencyRecord | None:
        return self._records.get(scope)

    def put(self, record: IdempotencyRecord) -> None:
        self._records[record.scope] = record


@dataclass(frozen=True, slots=True)
class IdempotencyDecision:
    """What the caller should do for one (scope, request_hash) pair."""

    is_replay: bool
    record: IdempotencyRecord | None


def check_idempotency(
    store: IdempotencyStorePort,
    scope: IdempotencyScope,
    request_hash: str,
    *,
    now: datetime,
) -> IdempotencyDecision:
    """Resolve scoped idempotency before any effect is attempted.

    - No record, or an expired one: proceed (``is_replay=False``) — the
      caller is free to overwrite an expired record with a fresh attempt.
    - A live record with the same canonical hash: replay. Return the
      original result; the caller must not invoke the adapter again.
    - A live record with a different hash: the key was reused for a
      different request in the same scope — fail closed
      (``IdempotencyConflictError``) rather than guess which request wins.
    """

    existing = store.get(scope)
    if existing is None or existing.expires_at <= now:
        return IdempotencyDecision(is_replay=False, record=None)
    if existing.request_hash != request_hash:
        raise IdempotencyConflictError(
            f"idempotency key {scope.key!r} for operation {scope.operation!r}"
            " was already used for a different request in this scope"
        )
    return IdempotencyDecision(is_replay=True, record=existing)


__all__ = [
    "IdempotencyDecision",
    "IdempotencyRecord",
    "IdempotencyScope",
    "IdempotencyStorePort",
    "InMemoryIdempotencyStore",
    "canonical_request_hash",
    "check_idempotency",
]

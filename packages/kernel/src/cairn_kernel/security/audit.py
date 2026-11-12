import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from cairn_kernel.hex import OperationClass, ProjectId, TenantId
from cairn_kernel.security.canonical import CanonicalJSONError, canonical_json, freeze_json


@dataclass(frozen=True, slots=True)
class AuditEntry:
    tenant_id: TenantId
    project_id: ProjectId | None
    actor: str
    action: str
    operation_class: OperationClass
    payload: Mapping[str, object]
    package_id: str | None = None
    correlation_id: str | None = None
    created_at: datetime | None = None
    payload_json: str = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        payload = dict(self.payload)
        if self.correlation_id is not None:
            payload.setdefault("correlation_id", self.correlation_id)
        try:
            canonical = canonical_json(payload)
            frozen = freeze_json(payload)
        except CanonicalJSONError as exc:
            raise CanonicalJSONError(f"audit payload is not canonical JSON: {exc}") from exc
        object.__setattr__(self, "payload_json", canonical)
        object.__setattr__(self, "payload", frozen)


def entry_hash(
    *,
    tenant_id: str,
    project_id: str | None,
    actor: str,
    action: str,
    operation_class: str,
    sequence: int,
    previous_hash: str | None,
    payload: str,
    created_at: str,
) -> str:
    material = canonical_json(
        {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "actor": actor,
            "action": action,
            "operation_class": operation_class,
            "sequence": sequence,
            "previous_hash": previous_hash,
            "payload": payload,
            "created_at": created_at,
        }
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


class AuditSink(Protocol):
    def append(self, entry: AuditEntry) -> str: ...


class MutationBoundary(Protocol):
    def execute(self, entry: AuditEntry, mutation: Callable[[Any], Any]) -> Any: ...

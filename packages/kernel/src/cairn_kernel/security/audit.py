from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from cairn_kernel.hex import OperationClass, ProjectId, TenantId


@dataclass(frozen=True, slots=True)
class AuditEntry:
    tenant_id: TenantId
    project_id: ProjectId | None
    actor: str
    action: str
    operation_class: OperationClass
    payload: dict[str, object]
    package_id: str | None = None
    correlation_id: str | None = None


class AuditSink(Protocol):
    def append(self, entry: AuditEntry) -> str: ...


class MutationBoundary(Protocol):
    def execute(self, entry: AuditEntry, mutation: Callable[[Any], Any]) -> Any: ...

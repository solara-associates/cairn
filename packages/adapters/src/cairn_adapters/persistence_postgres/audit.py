import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Generic, TypeVar

import psycopg
from cairn_kernel.errors import AuditUnavailableError
from cairn_kernel.security import AuditEntry
from psycopg import ClientCursor

ResultT = TypeVar("ResultT")


@dataclass(frozen=True, slots=True)
class MutationOutcome(Generic[ResultT]):
    result: ResultT
    audit_entry_id: str


def canonical_payload(payload: Mapping[str, object]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


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
) -> str:
    material = canonical_payload(
        {
            "tenant_id": tenant_id,
            "project_id": project_id,
            "actor": actor,
            "action": action,
            "operation_class": operation_class,
            "sequence": sequence,
            "previous_hash": previous_hash,
            "payload": payload,
        }
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _payload(entry: AuditEntry) -> str:
    payload = dict(entry.payload)
    if entry.correlation_id is not None:
        payload.setdefault("correlation_id", entry.correlation_id)
    return canonical_payload(payload)


def append_entry(connection: psycopg.Connection, entry: AuditEntry) -> str:
    tenant = entry.tenant_id.value
    project = None if entry.project_id is None else entry.project_id.value
    payload = _payload(entry)
    connection.execute(
        "SELECT pg_advisory_xact_lock(hashtext(%s))", (tenant,)
    )
    row = connection.execute(
        "SELECT sequence, entry_hash FROM ledger_entry"
        " WHERE tenant_id = %s ORDER BY sequence DESC LIMIT 1",
        (tenant,),
    ).fetchone()
    previous_hash = None if row is None else row[1]
    sequence = 1 if row is None else int(row[0]) + 1
    digest = entry_hash(
        tenant_id=tenant,
        project_id=project,
        actor=entry.actor,
        action=entry.action,
        operation_class=entry.operation_class.value,
        sequence=sequence,
        previous_hash=previous_hash,
        payload=payload,
    )
    entry_id = str(uuid.uuid4())
    connection.execute(
        "INSERT INTO ledger_entry (entry_id, tenant_id, project_id,"
        " package_id, sequence, entry_hash, previous_hash, actor,"
        " action, operation_class, payload)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
        (
            entry_id,
            tenant,
            project,
            entry.package_id,
            sequence,
            digest,
            previous_hash,
            entry.actor,
            entry.action,
            entry.operation_class.value,
            payload,
        ),
    )
    return entry_id


def _bind_context(
    connection: psycopg.Connection, assertion: str
) -> tuple[uuid.UUID, uuid.UUID | None]:
    connection.execute("SELECT cairn_set_tenant_context(%s)", (assertion,))
    tenant = connection.execute(
        "SELECT nullif(current_setting('app.tenant_id', true), '')::uuid"
    ).fetchone()
    project = connection.execute("SELECT cairn_current_project()").fetchone()
    if tenant is None or tenant[0] is None:
        raise AuditUnavailableError("tenant context is not established")
    project_id = None if project is None else project[0]
    if project_id is not None:
        connection.execute(
            "SELECT cairn_set_project_context(%s::uuid)", (project_id,)
        )
    return tenant[0], project_id


def _check_entry_scope(
    entry: AuditEntry, tenant: uuid.UUID, project: uuid.UUID | None
) -> None:
    if uuid.UUID(entry.tenant_id.value) != tenant:
        raise AuditUnavailableError("audit entry tenant is outside the assertion")
    entry_project = (
        None if entry.project_id is None else uuid.UUID(entry.project_id.value)
    )
    if entry_project != project:
        raise AuditUnavailableError("audit entry project is outside the assertion")


class PostgresAuditSink:
    def __init__(self, dsn: str, assertion: str) -> None:
        self._dsn = dsn
        self._assertion = assertion

    def append(self, entry: AuditEntry) -> str:
        try:
            connection = psycopg.connect(self._dsn, cursor_factory=ClientCursor)
            with connection, connection.transaction():
                tenant, project = _bind_context(connection, self._assertion)
                _check_entry_scope(entry, tenant, project)
                return append_entry(connection, entry)
        except (psycopg.Error, OSError) as exc:
            raise AuditUnavailableError("audit sink unavailable") from exc


class PostgresMutationBoundary:
    def __init__(self, dsn: str, assertion: str) -> None:
        self._dsn = dsn
        self._assertion = assertion

    def execute(
        self, entry: AuditEntry, mutation: Callable[[psycopg.Connection], ResultT]
    ) -> MutationOutcome[ResultT]:
        try:
            connection = psycopg.connect(self._dsn, cursor_factory=ClientCursor)
            with connection, connection.transaction():
                tenant, project = _bind_context(connection, self._assertion)
                _check_entry_scope(entry, tenant, project)
                result = mutation(connection)
                entry_id = append_entry(connection, entry)
                return MutationOutcome(result=result, audit_entry_id=entry_id)
        except (psycopg.Error, OSError) as exc:
            raise AuditUnavailableError("audit sink unavailable") from exc

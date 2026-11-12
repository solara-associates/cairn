import hashlib
import json
import uuid
from collections.abc import Mapping

import psycopg
from cairn_kernel.errors import AuditUnavailableError
from cairn_kernel.security import AuditEntry
from psycopg import ClientCursor


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


class PostgresAuditSink:
    def __init__(self, dsn: str, assertion: str) -> None:
        self._dsn = dsn
        self._assertion = assertion

    def append(self, entry: AuditEntry) -> str:
        tenant = entry.tenant_id.value
        project = None if entry.project_id is None else entry.project_id.value
        payload = canonical_payload(entry.payload)
        try:
            connection = psycopg.connect(self._dsn, cursor_factory=ClientCursor)
            with connection, connection.transaction():
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))", (tenant,)
                )
                connection.execute(
                    "SELECT cairn_set_tenant_context(%s)", (self._assertion,)
                )
                if project is not None:
                    connection.execute(
                        "SELECT cairn_set_project_context(%s::uuid)", (project,)
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
        except (psycopg.Error, OSError) as exc:
            raise AuditUnavailableError("audit sink unavailable") from exc
        return entry_id

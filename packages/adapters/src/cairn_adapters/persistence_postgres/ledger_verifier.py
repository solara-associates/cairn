import argparse
import json
import os
import uuid
from dataclasses import asdict, dataclass

import psycopg
from cairn_kernel.errors import AuditUnavailableError
from cairn_kernel.hex import TenantId
from cairn_kernel.security import canonical_json, entry_hash
from psycopg import ClientCursor

from cairn_adapters.persistence_postgres.audit import _bind_context


@dataclass(frozen=True, slots=True)
class LedgerVerificationReport:
    tenant_id: str
    entries_checked: int
    valid: bool
    first_invalid_sequence: int | None = None
    reason: str | None = None
    latest_hash: str | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def verify_ledger(
    connection: psycopg.Connection,
    tenant_id: TenantId,
    assertion: str,
    *,
    expected_latest_hash: str | None = None,
) -> LedgerVerificationReport:
    try:
        bound_tenant, _ = _bind_context(connection, assertion)
    except (psycopg.Error, OSError) as exc:
        raise AuditUnavailableError("ledger verification unavailable") from exc
    if bound_tenant != uuid.UUID(tenant_id.value):
        raise ValueError("verification tenant does not match the assertion")
    rows = connection.execute(
        "SELECT entry_id, tenant_id, project_id, sequence, entry_hash,"
        " previous_hash, actor, action, operation_class, payload, created_at"
        " FROM ledger_entry WHERE tenant_id = %s ORDER BY sequence",
        (tenant_id.value,),
    ).fetchall()

    previous_hash: str | None = None
    expected_sequence = 1
    latest_hash: str | None = None
    for row in rows:
        (
            _entry_id,
            row_tenant,
            row_project,
            sequence,
            stored_hash,
            stored_previous,
            actor,
            action,
            operation_class,
            payload,
            created_at,
        ) = row
        sequence = int(sequence)
        if sequence != expected_sequence:
            return _invalid(
                tenant_id, expected_sequence - 1, "sequence gap or out of order"
            )
        if stored_previous != previous_hash:
            return _invalid(tenant_id, sequence - 1, "previous hash mismatch")
        recomputed = entry_hash(
            tenant_id=str(row_tenant),
            project_id=None if row_project is None else str(row_project),
            actor=actor,
            action=action,
            operation_class=operation_class,
            sequence=sequence,
            previous_hash=stored_previous,
            payload=canonical_json(payload),
            created_at=created_at.isoformat(),
        )
        if recomputed != stored_hash:
            return _invalid(tenant_id, sequence - 1, "entry hash mismatch")
        previous_hash = stored_hash
        latest_hash = stored_hash
        expected_sequence += 1
    if expected_latest_hash is not None and latest_hash != expected_latest_hash:
        return LedgerVerificationReport(
            tenant_id=tenant_id.value,
            entries_checked=len(rows),
            valid=False,
            reason="latest hash does not match the trusted anchor",
            latest_hash=latest_hash,
        )
    return LedgerVerificationReport(
        tenant_id=tenant_id.value,
        entries_checked=len(rows),
        valid=True,
        latest_hash=latest_hash,
    )


def _invalid(
    tenant_id: TenantId, last_valid_sequence: int, reason: str
) -> LedgerVerificationReport:
    first_invalid = last_valid_sequence + 1
    return LedgerVerificationReport(
        tenant_id=tenant_id.value,
        entries_checked=last_valid_sequence,
        valid=False,
        first_invalid_sequence=first_invalid,
        reason=reason,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="cairn-verify-ledger",
        description="Verify a tenant audit ledger hash chain.",
    )
    parser.add_argument("--dsn", default=os.environ.get("CAIRN_DATABASE_URL"))
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--assertion", required=True)
    parser.add_argument("--expected-hash", default=None)
    args = parser.parse_args(argv)
    if not args.dsn:
        print("cairn-verify-ledger: set CAIRN_DATABASE_URL or pass --dsn")
        return 2
    with psycopg.connect(args.dsn, cursor_factory=ClientCursor) as connection:
        report = verify_ledger(
            connection,
            TenantId(args.tenant),
            args.assertion,
            expected_latest_hash=args.expected_hash,
        )
    print(json.dumps(report.to_dict(), sort_keys=True))
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())

# CA-003: transactional audit boundary

## Problem

The audit sink existed but nothing tied it to a mutation. A business write could commit while its audit event failed, and callers could write through arbitrary connections with no audit at all.

## Decision

Business mutations and their audit events share one database transaction.

- `PostgresMutationBoundary.execute(entry, mutation)` opens a transaction, binds the signed tenant context, runs the mutation callback with the transaction connection, appends the audit entry through the same connection, and commits. Any failure rolls both back.
- The entry scope must match the signed assertion. A mismatch fails before anything is written.
- `MutationOutcome` returns the mutation result and the audit entry id, so API handlers can emit `x-cairn-audit-id`.
- Audit payloads carry `correlation_id` when set on the entry, plus caller-provided before and after references.
- `append_entry` is the only ledger writer. The standalone `PostgresAuditSink` wraps it for non-mutating writes.

## Rule for future repositories

Every repository write method takes an open `psycopg.Connection` supplied by the boundary. Repositories must not open their own connection or DSN. The boundary is the only protected mutation path, and a repository that needs a connection must be called from inside `execute`.

## Acceptance evidence

`tests/integration/test_mutation_boundary.py`:

- mutation and audit entry commit together, with actor, action, operation class, correlation id and references recorded;
- an audit failure rolls the business write back and leaves no ledger row;
- a business failure writes no audit event;
- an entry whose tenant or project is outside the assertion is rejected;
- a forged assertion fails closed;
- successive mutations extend the tenant chain with sequences 1 and 2.

Existing sink tests confirm that standalone audit writes remain fail-closed.

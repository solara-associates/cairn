# CA-006: migration serialization

## Problem

Two migration processes could interleave. Each step reconnected, read the applied set, and applied a migration in its own transaction, so concurrent deployments could race on the same version.

## Decision

`Migrator.up()` and `Migrator.down()` hold a Postgres session advisory lock (`pg_advisory_lock`, key `0x636169726E`) on a dedicated connection for the whole operation, including validation, each migration step and each history record.

- A second migrator blocks until the first releases the lock.
- The lock connection is separate from the per-migration transaction connections, so a migration failure does not leave an open write transaction.
- The lock is released in a `finally` path (explicit `pg_advisory_unlock`, and connection close as a backstop).
- `status` does not take the lock; it is read-only.

## Acceptance evidence

`tests/integration/test_migration_lock.py`:

- `up` blocks while another session holds the lock and completes with all migrations after release;
- two concurrent `up` runs apply each migration exactly once;
- `down` blocks on the same lock and reverts after release;
- a failing migration releases the lock, proven by a successful `pg_try_advisory_lock` afterwards.

Full suite green, `make lint` green.

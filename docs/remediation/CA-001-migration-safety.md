# CA-001: migration safety

## Problem

`Migrator.down()` reverted every applied migration without a target. A routine rollback could drop foundational tables, and no execution record identified who ran what, when, or whether it succeeded.

## Decision

- Rollback requires an explicit target version (`--to`); the baseline is `0000`.
- One step is the default. Multi-step rollback requires `allow_multiple`.
- Down scripts are scanned for destructive statements: `DROP` of tables, columns, schemas, types, functions, indexes, triggers or policies, plus `TRUNCATE` and `DELETE FROM`.
- Destructive rollback requires `allow_destructive`. When `CAIRN_ENVIRONMENT` is `production` or `prod`, it also requires a recovery reference.
- Each migration attempt inserts a row in `schema_migration_history` with version, name, direction, outcome, operator and timestamp. Failures are recorded on a separate connection so the record survives the rollback, and the ledger row is only removed in the same transaction that reverts the schema.
- Operator identity comes from `operator=`, then `CAIRN_MIGRATION_OPERATOR`, then the operating system user.

## Commands

```
cairn-migrate up
cairn-migrate down --to 0002 --allow-destructive
cairn-migrate down --to 0000 --allow-multiple --allow-destructive --recovery-reference OPS-1234
```

`make migrate-down VERSION=0002` requires the version.

## Acceptance evidence

`tests/integration/test_migration_safety.py`:

- rollback without `--to` exits 2;
- unknown and unapplied targets are rejected;
- single step is the default and multi-step needs opt-in;
- destructive rollback is refused without the flag, and in production without a recovery reference;
- rollback preserves tenant and project rows and records operator and outcome;
- a failed down script leaves the schema and ledger consistent, records the failure, and the migration can be reverted after repair.

`tests/integration/test_migrations.py` covers the full up/down round trip with the new targeting rules.

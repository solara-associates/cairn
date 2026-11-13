# Backup and restore

Status: Evidenced for the Cloud SQL (Postgres) OLTP store and the evidence
bucket's retention configuration. Proven by a dry run against a local
Postgres test container, not a live GCP instance — no cloud account exists
for this repository. The restore mechanics (pg_dump/pg_restore round trip,
data-integrity check) are the same ones a human operator runs by hand;
Cloud SQL's managed backup/PITR replaces the "take a backup" step with an
automatic one, the restore and verification steps below are unchanged.

## What is backed up

| Store | Mechanism | Where it's declared |
| :- | :- | :- |
| Cloud SQL (PostgreSQL) — tenants, projects, users, roles, connections, job state, approvals, evidence indices, mapping release metadata, audit (ADR-007) | Automated daily backups **and** point-in-time recovery (PITR), both enabled on the instance | `infra/terraform/modules/cairn-data/main.tf`, `google_sql_database_instance.cairn.settings.backup_configuration` (`enabled = true`, `point_in_time_recovery_enabled = true`) |
| Evidence package bucket (ADR-008) — signed JSON evidence packages | Object versioning, access logging, and a retention policy (unlocked until the residency matrix in spec §13.6 is approved — see gate 11) | `infra/terraform/modules/cairn-evidence/main.tf`, `google_storage_bucket.evidence` |
| BigQuery (raw/curated/consumption analytics; ADR-007) | Derived from Postgres/events, not an independent source of truth — no backup/restore procedure of its own is needed; re-deriving from Postgres is the recovery path | `infra/terraform/modules/cairn-data/main.tf`, `google_bigquery_dataset.cairn` |

**Checked during this unit:** PITR was already `enabled = true` in
`cairn-data`'s Terraform before this change — nothing needed fixing there.
See `~/solara/lz2026/s652-handover.md` for the full note to Allan.

## Pre-flight checks before a restore

1. Confirm the target environment and instance name — a restore to the
   wrong Cloud SQL instance is irreversible for whatever it overwrites.
2. Confirm which recovery point is wanted: the latest automated backup, or a
   specific point in time (PITR). PITR requires a target timestamp inside
   the configured retention window.
3. Confirm no migration is in flight (`schema_migration` ledger has no
   pending lock — see `tools/ops` / `make migrate`) — restoring mid-migration
   produces a schema that doesn't match any migration version.
4. Take (or confirm there already exists) a fresh backup of the *current*
   state before restoring over it, in case the restore target turns out to
   be wrong.
5. Notify anyone with an open session against the instance; a restore
   terminates existing connections.

## Restore procedure

1. Identify the recovery point (backup id, or PITR timestamp).
2. Restore into a **new** instance/database first — never restore in place
   over the live instance. This is the same shape proven by the dry run
   below: restore into a fresh target, verify it, then promote/cut over.
3. Run the schema migration ledger check (`schema_migration` /
   `schema_migration_history` tables) against the restored database and
   confirm it matches the version the application expects.
4. Verify data integrity: row counts and a content check on the
   tenant-scoped tables that matter most (tenant, project, audit,
   evidence indices) against the last-known-good state.
5. Verify the evidence chain is still intact: run `verify_chain` (see
   `packages/kernel/src/cairn_kernel/evidence/verify.py`) over the evidence
   indices in the restored database and confirm `PASS`.
6. Only once 3–5 pass, cut the application over to the restored
   instance/database and decommission the old one.

## What is tested, and how

`tools/ops/backup_restore_dry_run.py` runs the restore procedure's testable
core end to end against the same local Postgres test container
`tests/integration/` already uses (started fresh via Docker, or pointed at
`CAIRN_TEST_DATABASE_URL` when CI provides one):

1. Migrates a throwaway database to the current schema (the same
   `Migrator` used in production).
2. Seeds deterministic rows into `tenant` and `project` and hashes their
   content.
3. Runs `pg_dump` (the testable analog of a Cloud SQL backup/PITR
   snapshot) into a backup file.
4. Restores that backup into a **separate**, fresh database with
   `pg_restore` — proving step 2 of the restore procedure above (restore
   into a new target, not in place).
5. Re-hashes the restored content and asserts it is identical to the
   pre-backup hash — this is the data-integrity check from step 4 above,
   made executable instead of only described.

Run it directly:

```bash
uv run python tools/ops/backup_restore_dry_run.py
```

It is also run in CI on every pull request (see `.github/workflows/ci.yml`,
job `backup-restore-dry-run`) so a change that breaks the restore path fails
the same gate as any other test, instead of being discovered during a real
incident.

## Known gaps

- The dry run exercises Postgres only. The evidence bucket's own recovery
  path (GCS object versioning / retention) is declared in Terraform but has
  no corresponding restore drill in this repository — there is no local GCS
  emulator wired into the test suite yet. Flagged, not silently assumed
  equivalent.
- The retention policy on the evidence bucket (`is_locked = false`) is
  intentionally unlocked until gate 11 (the residency matrix) is approved —
  see `infra/terraform/modules/cairn-evidence/main.tf`.

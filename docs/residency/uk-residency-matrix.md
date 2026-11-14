# UK data, backup, key and support-access residency matrix

R0-20 gate 11 (spec §16.0, row 11: "UK data, backup, key and support-access
residency matrix approved").

Session s654 drafted this matrix against what was true in code and Terraform
at the time, with three `[ALLAN: decide]` items open. Session s678
(2026-11-14) records Allan's decisions against all three and encodes what
Terraform and a test can check. With all three decided, this matrix moves
from Partial to **Approved** (see `docs/acceptance/r0-20-review.md` row 11).

Repo state reviewed: `origin/main` @ `da1033e` (s654); updated against
`origin/main` @ `f754ec8` (s678).

Related: ADR-016 (launch jurisdiction — UK, `europe-west2`) decided *which*
jurisdiction pack CAIRN launches with and that a pack is data, not code. This
matrix does not reopen that decision; it documents the residency facts that
follow from it, row by row.

## Allan's decisions (2026-11-14)

1. **Customer data and backups are UK only.** Primary and backups live in
   `europe-west2` (London), multi-zone, with no copy outside the UK. GCP
   has a single UK region, so region-level disaster recovery inside the UK
   is not available — backups are multi-zone within London, not a
   second-region failover.
2. **Encryption keys stay in the UK only.**
3. **Support access to customer data is not restricted by location.** Any
   authorised staff member may access it from anywhere, provided every
   access is logged, approved and auditable.

## Matrix

| Area | Status | Fact / code reference |
|---|---|---|
| **Data location** (Cloud SQL, BigQuery) | Approved — Fact, matches decision 1 | `google_sql_database_instance.cairn` in `infra/terraform/modules/cairn-data/main.tf` sets `region = var.region`; `google_bigquery_dataset.cairn` sets `location = var.region`. `var.region` defaults to `"europe-west2"` in `infra/terraform/envs/dev/variables.tf`, matching ADR-016. (Staging/prod environments, if and when they exist, must set the same `region` default or an equivalent override — not yet verified, since only `envs/dev` exists today.) |
| **Evidence / object storage location** | Approved — Fact, matches decision 1 | `cairn-evidence` module: `google_kms_key_ring.evidence.location = var.region` and `google_storage_bucket.evidence.location = var.region`. The general-purpose buckets in `cairn-data` (`raw`/`artifacts`) also set `location = var.region`. All resolve to `europe-west2`. Same staging/prod caveat as above. |
| **Backup location** (Cloud SQL automated backups / PITR) | Approved — now pinned in Terraform | `backup_configuration` in `infra/terraform/modules/cairn-data/main.tf` now sets `location = var.region` explicitly (previously unset, left to Cloud SQL's own default). `tests/conformance/test_uk_residency.py::test_cloudsql_backups_are_pinned_to_the_instance_region` fails the build if that pin is ever removed or pointed somewhere other than `var.region`. Multi-zone resilience within `europe-west2` comes from `cloudsql_availability_type = "REGIONAL"` (documented in `infra/terraform/modules/cairn-data/variables.tf` as the staging/prod setting; dev stays `ZONAL` deliberately, per decision 1's note that there is no second UK region to fail over to regardless). No backup/restore runbook has landed yet (`docs/runbooks/` on `origin/main` still only has `.gitkeep`) — when it lands, its claims must be checked against this row. |
| **Key residency** (KMS evidence-signing key) | Approved — now a stated commitment, not just today's default | `google_kms_key_ring.evidence` and `google_kms_crypto_key.evidence_signing` in `infra/terraform/modules/cairn-evidence/main.tf` both resolve to `var.region`; the module now carries an explicit comment recording decision 2 as a standing commitment for this key and any future CAIRN-held key, not merely today's Terraform default. The only IAM binding on the key is `roles/cloudkms.signerVerifier` for the signer service account — no export permission is granted. `tests/conformance/test_uk_residency.py::test_evidence_signing_key_is_pinned_to_the_uk_region_with_no_export_grant` fails the build if the key's location pin is removed or an export-capable role is ever granted on it. |
| **Support-access residency** | Approved as policy; audited-access mechanism not yet built | Decision 3 removes any location restriction, replacing it with a logged/approved/auditable requirement. No ADR, Terraform module, or IAM policy in this repo currently provisions human support access to customer data at all — `infra/terraform/modules/cairn-iam` provisions only workload-identity service accounts, and `infra/terraform/modules/cairn-connections` is a read-only customer-environment connection role, neither for human support staff. Because no such path exists yet, `tests/conformance/test_uk_residency.py::test_no_human_or_group_principal_is_granted_direct_data_access` guards against one being added silently: no `user:`/`group:`/`domain:` IAM principal may appear anywhere in `infra/terraform`. The day a support-access feature is built, it must go through an audited, approved path (logged, approved, auditable per decision 3) — that build is not scoped to any R0-R5 story in `CAIRN-TECHNICAL-IMPLEMENTATION-SPEC.md` today, so it is flagged here for a future story rather than invented now. |

## What this matrix is not

- Not a reopening of ADR-016. The jurisdiction (UK, `europe-west2`) and the
  "pack is data, not code" decision stand as ADR-016 recorded them.
- Not a staging/prod verification. Everything marked "Fact" above is only
  confirmed for `infra/terraform/envs/dev`; no staging or prod Terraform
  environment exists in this repo to check against.
- Not a backup/restore runbook. `docs/runbooks/backup-restore.md` does not
  exist on `origin/main` as of this matrix; when it lands, its backup
  storage-location claims must be checked against this matrix's backup row.
- Not a support-access feature. Decision 3 is a policy commitment about how
  support access must work when it exists; this session does not build a
  support-access tool, and the guard test above enforces only that no
  ungated path is added before one does.

## Decisions (verbatim, for tracking)

1. Decided — Backup location: Cloud SQL automated-backup / PITR storage is
   pinned to `europe-west2` explicitly in Terraform.
2. Decided — Key residency: CAIRN commits, as policy, to never exporting or
   rotating the evidence-signing key (or any future CAIRN-held key) through
   a non-UK KMS location.
3. Decided — Support-access residency: any authorised staff member may
   access customer data for support from anywhere; no location restriction
   applies, but every access must be logged, approved and auditable. The
   mechanism enforcing that for a real support-access feature is not yet
   built (no owning story exists today); until it exists, the no-ungated-
   access guard above is what's enforced.

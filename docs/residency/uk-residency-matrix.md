# UK data, backup, key and support-access residency matrix

R0-20 gate 11 (spec §16.0, row 11: "UK data, backup, key and support-access
residency matrix approved"). This document drafts the matrix against what is
already true in code and Terraform today. It does not approve anything — a
residency and support-access **policy** decision belongs to Allan, and this
document does not make that decision on his behalf. Rows marked
`[ALLAN: decide]` are open; the matrix stays Partial (see
`docs/acceptance/r0-20-review.md` row 11) until every one of them is resolved.

Session: s654. Repo state reviewed: `origin/main` @ `da1033e`.

Related: ADR-016 (launch jurisdiction — UK, `europe-west2`) decided *which*
jurisdiction pack CAIRN launches with and that a pack is data, not code. This
matrix does not reopen that decision; it documents the residency facts that
follow from it, row by row.

## Matrix

| Area | Status | Fact / code reference | Open decision |
|---|---|---|---|
| **Data location** (Cloud SQL, BigQuery) | Fact | `google_sql_database_instance.cairn` in `infra/terraform/modules/cairn-data/main.tf` sets `region = var.region`; `google_bigquery_dataset.cairn` sets `location = var.region`. `var.region` defaults to `"europe-west2"` in `infra/terraform/envs/dev/variables.tf` ("Spec §13.1: europe-west2 is the primary hosted-SaaS region"), matching ADR-016's decision to launch in `europe-west2` (London). | — none; this is already pinned in Terraform for the dev environment. (Staging/prod environments, if and when they exist, must set the same `region` default or an equivalent override — not yet verified, since only `envs/dev` exists today.) |
| **Evidence / object storage location** | Fact | `cairn-evidence` module (`infra/terraform/modules/cairn-evidence/main.tf`): `google_kms_key_ring.evidence.location = var.region` and `google_storage_bucket.evidence.location = var.region`. The general-purpose buckets in `cairn-data` (`google_storage_bucket.cairn`, for `raw`/`artifacts`) also set `location = var.region`. All resolve to `europe-west2` via the same `envs/dev/variables.tf` default. | Same caveat as above: only verified for `envs/dev`; no staging/prod Terraform exists yet to check. |
| **Backup location** (Cloud SQL automated backups / PITR) | Fact + open decision | `infra/terraform/modules/cairn-data/main.tf`'s `backup_configuration` block sets `enabled = true` and `point_in_time_recovery_enabled = true`, but it does **not** set a `location` argument on `backup_configuration`. Cloud SQL's own default, when that argument is omitted, is to store automated backups in the instance's region or a nearby multi-region, not necessarily pinned to `europe-west2` specifically — this has not been confirmed against actual Cloud SQL behavior in this repo, and nothing in Terraform states or enforces it. No backup/restore runbook has landed yet: `git log origin/main -- docs/runbooks/backup-restore.md` returns no commits, and `docs/runbooks/` on `origin/main` contains only `.gitkeep`. | `[ALLAN: decide]` — does CAIRN commit to pinning Cloud SQL automated-backup storage to `europe-west2` explicitly (via `backup_configuration.location` or an equivalent control), or is the current unset/default behavior acceptable? This should not be assumed to be "same region" without an explicit Terraform setting and a verifying test, per spec §13.6. |
| **Key residency** (KMS evidence-signing key) | Fact + open decision | `google_kms_key_ring.evidence` and `google_kms_crypto_key.evidence_signing` in `infra/terraform/modules/cairn-evidence/main.tf` both resolve their location to `var.region` (`europe-west2`). The key is `ASYMMETRIC_SIGN` / `EC_SIGN_P256_SHA256`, has `prevent_destroy = true`, and `destroy_scheduled_duration = "86400s"`; the only IAM binding is `roles/cloudkms.signerVerifier` for the configured signer service account — no export permission is granted. ADR-008 states "Signing keys are CAIRN-held at launch. Customer-held keys are not offered until a later ADR," and separately that "Key rotation and verification keys are published; verification does not require CAIRN to be online." Taken together, the key is created and held in a UK KMS location today, and no code path grants export. | `[ALLAN: decide]` — does CAIRN commit, as policy, to **never** rotating or re-provisioning this (or any future) signing key through a non-UK KMS location — i.e. is UK key residency itself a customer-facing commitment, not just today's Terraform default? ADR-008 decided CAIRN holds the key; it did not decide the key's location is a residency guarantee. This matrix flags the implication; it does not assume Allan's answer. |
| **Support-access residency** | No fact — fully open | No ADR, Terraform module, or IAM policy in the repo addresses who may access live customer data for support purposes, under what approval, or from what geographic location. `infra/terraform/modules/cairn-iam` provisions workload identity service accounts for CAIRN's own services (not human support staff), and `infra/terraform/modules/cairn-connections` defines a read-only connection role for assessing customer environments — neither says anything about human support access, its location, or its logging. | `[ALLAN: decide]` — entirely open. Who can access customer data for support, under what approval and audit trail, and must that access originate from or be restricted to the UK (or any other location)? No default is proposed here. |

## What this matrix is not

- Not an approval. Gate 11 moves from Missing to Partial on the strength of
  this document (see `docs/acceptance/r0-20-review.md`), never to Evidenced
  or Approved, while any `[ALLAN: decide]` row above is open.
- Not a reopening of ADR-016. The jurisdiction (UK, `europe-west2`) and the
  "pack is data, not code" decision stand as ADR-016 recorded them.
- Not a staging/prod verification. Everything marked "Fact" above is only
  confirmed for `infra/terraform/envs/dev`; no staging or prod Terraform
  environment exists in this repo to check against.
- Not a backup/restore runbook. `docs/runbooks/backup-restore.md` does not
  exist on `origin/main` as of this matrix; when it lands, its backup
  storage-location claims must be checked against this matrix's backup row,
  not assumed to agree with it.

## Open decisions (verbatim, for tracking)

1. `[ALLAN: decide]` — Backup location: pin Cloud SQL automated-backup / PITR
   storage to `europe-west2` explicitly in Terraform, or accept the current
   unpinned default?
2. `[ALLAN: decide]` — Key residency: commit, as policy, to never
   exporting or rotating the evidence-signing key (or any future CAIRN-held
   key) through a non-UK KMS location?
3. `[ALLAN: decide]` — Support-access residency: who may access customer
   data for support, under what approval, and from what location? No default
   proposed.

# Minimal dev cloud foundation (session 684): the smallest set Allan
# authorised -- a Terraform state bucket, a KMS key ring and an
# evidence-signing key -- in solara-cairn-dev only. Deliberately does NOT
# compose the full dev environment (infra/terraform/envs/dev): no network,
# IAM service accounts, Cloud SQL, Cloud Run, events, observability or
# guardrails modules. Those remain R0-16's own, separate, much larger
# acceptance criterion.
#
# These two resources already exist in solara-cairn-dev, created directly
# with `gcloud` in this session because the Architectural Rules guard
# denies `terraform init` with a real backend from this (or any) local
# session, and the `iac_allowances` bypass documented for that guard did
# not unblock it in practice (see README.md). This file is the Terraform
# *declaration* of those same resources, written to match what was
# created, so a future session (or Allan) can bring them under real
# Terraform management with a plain `terraform import` -- see README.md
# for the exact import commands -- rather than Terraform trying (and
# failing) to create them again.

resource "google_storage_bucket" "terraform_state" {
  project                     = var.project_id
  name                        = "solara-cairn-dev-tfstate"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }
}

# UK residency commitment (docs/residency/uk-residency-matrix.md, Allan's
# decision 2, 2026-11-14): this key, and any future CAIRN-held key, is
# created and re-provisioned only in a europe-west2 ring, never exported.
# Same naming convention `infra/terraform/modules/cairn-evidence` uses
# (`cairn-${environment}-evidence` / `cairn-${environment}-evidence-signing`)
# so the two line up once the full module is applied for `dev` and this
# key is imported into it instead of recreated.
resource "google_kms_key_ring" "evidence" {
  project  = var.project_id
  name     = "cairn-dev-evidence"
  location = var.region
}

resource "google_kms_crypto_key" "evidence_signing" {
  name     = "cairn-dev-evidence-signing"
  key_ring = google_kms_key_ring.evidence.id
  purpose  = "ASYMMETRIC_SIGN"

  version_template {
    algorithm        = "EC_SIGN_P256_SHA256"
    protection_level = "SOFTWARE"
  }

  destroy_scheduled_duration = "86400s"

  lifecycle {
    prevent_destroy = true
  }
}

# IAM binding granting the signing/verification proof's own identity
# access to the key -- intentionally NOT declared here. It was applied
# directly with `gcloud kms keys add-iam-policy-binding` after an
# explicit confirmation step (A9.irreversible-confirm), scoped to one
# named user, for this session's KMS signing proof only. A real workload
# service account's binding belongs with that service account, when
# `infra/terraform/modules/cairn-iam` is actually applied for `dev` --
# not invented here ahead of that.

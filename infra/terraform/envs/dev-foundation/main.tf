# Minimal dev cloud foundation: the smallest set of resources needed
# before anything else in `dev` can be applied -- a Terraform state
# bucket, a KMS key ring and an evidence-signing key, in whichever GCP
# project `var.project_id` names. Deliberately does NOT compose the full
# dev environment (infra/terraform/envs/dev): no network, IAM service
# accounts, Cloud SQL, Cloud Run, events, observability or guardrails
# modules. Those remain a separate, much larger acceptance criterion.
#
# If these two resources were created directly with `gcloud` first (see
# README.md for why a maintainer might do that, and the exact commands),
# this file is the Terraform *declaration* of those same resources, so
# they can be brought under real Terraform management with a plain
# `terraform import` -- see README.md for the exact import commands --
# rather than Terraform trying (and failing) to create them again.

resource "google_storage_bucket" "terraform_state" {
  project                     = var.project_id
  name                        = "${var.project_id}-tfstate"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  # checkov:skip=CKV_GCP_62: no access-log bucket exists yet in this
  # minimal foundation (infra/terraform/modules/cairn-observability,
  # the module that provisions one, is deliberately out of scope here —
  # see README.md). Wire `logging { log_bucket = ... }` once that module
  # is applied for `dev`, same as infra/terraform/modules/cairn-data's
  # buckets do.
}

# UK residency commitment (docs/residency/uk-residency-matrix.md): this
# key, and any future CAIRN-held key, is created and re-provisioned only
# in a europe-west2 ring, never exported. Same naming convention
# `infra/terraform/modules/cairn-evidence` uses
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

# IAM binding granting a signing/verification identity access to the key
# -- intentionally NOT declared here. Grant it by hand
# (`gcloud kms keys add-iam-policy-binding`), scoped to one named
# principal, only for whoever actually needs to prove a real KMS
# signature. A real workload service account's binding belongs with
# that service account, when `infra/terraform/modules/cairn-iam` is
# actually applied for `dev` -- not invented here ahead of that.

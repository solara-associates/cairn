# KMS signing key and the immutable evidence bucket.
# Spec §13.3 "cairn-evidence": KMS keys, immutable bucket, audit sink.
# ADR-008: evidence packages are hash-chained and signed with a KMS-held key.
# The key never leaves KMS — nothing here is a long-lived exportable secret.

resource "google_kms_key_ring" "evidence" {
  project  = var.project_id
  name     = "cairn-${var.environment}-evidence"
  location = var.region
}

resource "google_kms_crypto_key" "evidence_signing" {
  name     = "cairn-${var.environment}-evidence-signing"
  key_ring = google_kms_key_ring.evidence.id
  purpose  = "ASYMMETRIC_SIGN"

  version_template {
    algorithm = "EC_SIGN_P256_SHA256"
  }

  # Evidence signatures must stay verifiable for the life of the chain;
  # never destroy a signing key version automatically.
  destroy_scheduled_duration = "86400s"

  lifecycle {
    prevent_destroy = true
  }
}

resource "google_kms_crypto_key_iam_member" "signer" {
  crypto_key_id = google_kms_crypto_key.evidence_signing.id
  role          = "roles/cloudkms.signerVerifier"
  member        = "serviceAccount:${var.signer_service_account_email}"
}

resource "google_storage_bucket" "evidence" {
  project                     = var.project_id
  name                        = "cairn-evidence-${var.environment}"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  logging {
    log_bucket = var.access_log_bucket_name
  }

  retention_policy {
    retention_period = var.retention_period_seconds
    is_locked        = false # locked only once the residency matrix (spec §13.6) is approved for this environment
  }
}

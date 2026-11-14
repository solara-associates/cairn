output "terraform_state_bucket" {
  value = google_storage_bucket.terraform_state.name
}

output "evidence_key_ring_id" {
  value = google_kms_key_ring.evidence.id
}

output "evidence_signing_key_id" {
  value = google_kms_crypto_key.evidence_signing.id
}

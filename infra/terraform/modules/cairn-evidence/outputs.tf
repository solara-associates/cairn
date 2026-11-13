output "signing_key_id" {
  value = google_kms_crypto_key.evidence_signing.id
}

output "evidence_bucket_name" {
  value = google_storage_bucket.evidence.name
}

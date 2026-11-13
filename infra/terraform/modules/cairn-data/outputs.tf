output "cloudsql_connection_name" {
  value = google_sql_database_instance.cairn.connection_name
}

output "cloudsql_private_ip" {
  value = google_sql_database_instance.cairn.private_ip_address
}

output "bigquery_dataset_ids" {
  value = { for k, d in google_bigquery_dataset.cairn : k => d.dataset_id }
}

output "gcs_bucket_names" {
  value = { for k, b in google_storage_bucket.cairn : k => b.name }
}

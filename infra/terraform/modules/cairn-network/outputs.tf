output "network_id" {
  description = "Self-link of the CAIRN VPC for this environment."
  value       = google_compute_network.cairn.id
}

output "network_name" {
  value = google_compute_network.cairn.name
}

output "subnet_id" {
  value = google_compute_subnetwork.primary.id
}

output "subnet_self_link" {
  value = google_compute_subnetwork.primary.self_link
}

output "private_service_access_connection" {
  description = "Used by cairn-data to make Cloud SQL / Memorystore depend on PSA being established first."
  value       = google_service_networking_connection.private_service_access.id
}

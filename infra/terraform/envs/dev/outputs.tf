output "network_name" {
  value = module.network.network_name
}

output "cloudsql_connection_name" {
  value = module.data.cloudsql_connection_name
}

output "service_uris" {
  value = module.runtime.service_uris
}

output "evidence_bucket_name" {
  value = module.evidence.evidence_bucket_name
}

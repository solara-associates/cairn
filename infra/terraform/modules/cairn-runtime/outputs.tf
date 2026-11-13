output "service_uris" {
  value = { for k, s in google_cloud_run_v2_service.service : k => s.uri }
}

output "job_names" {
  value = { for k, j in google_cloud_run_v2_job.job : k => j.name }
}

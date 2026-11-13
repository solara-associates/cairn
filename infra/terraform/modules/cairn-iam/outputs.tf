output "service_account_emails" {
  description = "Map of workload name to its Workload Identity service account email."
  value       = { for k, sa in google_service_account.workload : k => sa.email }
}

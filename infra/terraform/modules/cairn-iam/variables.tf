variable "project_id" {
  description = "GCP project ID to create service accounts and bindings in."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod) used in resource naming."
  type        = string
}

variable "workload_service_accounts" {
  description = <<-EOT
    One Workload-Identity service account per CAIRN runtime workload (spec §13.1:
    cairn-api, cairn-worker, cairn-mcp-gateway, cairn-scheduler, cairn-ingest-job,
    cairn-assess-job, cairn-transform-job). Key is the short workload name, value
    is the list of least-privilege project IAM roles that workload needs.
  EOT
  type        = map(list(string))
}

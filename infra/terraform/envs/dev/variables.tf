variable "project_id" {
  description = "GCP project ID for the dev environment. Allan must create/name this project; see README.md."
  type        = string
}

variable "region" {
  description = "Spec §13.1: europe-west2 is the primary hosted-SaaS region."
  type        = string
  default     = "europe-west2"
}

variable "billing_account_id" {
  description = "Billing account the dev project is attached to."
  type        = string
}

variable "notification_email" {
  description = "Address that receives dev alerts and budget notifications."
  type        = string
}

variable "workload_image" {
  description = <<-EOT
    Placeholder container image used by every Cloud Run service/job until
    apps/api, apps/worker, apps/mcp-gateway and apps/console (R0-15) are
    built and pushed to Artifact Registry. Defaults to a public Google
    sample image so this environment is internally consistent without
    requiring a registry push first.
  EOT
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "evidence_retention_period_seconds" {
  description = "Dev default: 1 day, short enough to tear down easily. Staging/prod must use the retention period from the approved residency matrix (spec §13.6), not this default."
  type        = number
  default     = 86400
}

variable "monthly_budget_amount_units" {
  description = "Dev spend cap in budget_currency_code units."
  type        = number
  default     = 100
}

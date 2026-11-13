variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "environment" {
  type = string
}

variable "signer_service_account_email" {
  description = "Workload identity (from cairn-iam) allowed to sign with the evidence key, e.g. the worker service account."
  type        = string
}

variable "access_log_bucket_name" {
  description = "Destination bucket (from cairn-observability) that the evidence bucket's access logs are written to."
  type        = string
}

variable "retention_period_seconds" {
  description = "Evidence bucket retention lock duration (spec §13.1: immutable). Long enough to outlast the UK residency retention requirement; confirm the figure against the approved residency matrix (spec §13.6) before applying."
  type        = number
}

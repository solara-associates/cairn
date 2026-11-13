variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "environment" {
  type = string
}

variable "log_sink_destination" {
  description = "Destination for the project log sink, e.g. a BigQuery dataset self-link from cairn-data."
  type        = string
}

variable "notification_email" {
  description = "Email address alert policies page. Solo-maintainer on-call per spec §13.6 — not a secret, but keep it out of version-controlled defaults; pass via tfvars."
  type        = string
}

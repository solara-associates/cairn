variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "environment" {
  type = string
}

variable "network_id" {
  description = "Self-link of the VPC from cairn-network, for Cloud SQL private IP."
  type        = string
}

variable "private_service_access_connection" {
  description = "The cairn-network PSA connection, so Cloud SQL is created after peering exists."
  type        = string
}

variable "cloudsql_tier" {
  description = "Cloud SQL machine tier. Keep this small in dev; size up per environment."
  type        = string
  default     = "db-g1-small"
}

variable "cloudsql_availability_type" {
  description = "ZONAL in dev, REGIONAL (HA) in staging/prod per spec §13.1."
  type        = string
  default     = "ZONAL"
}

variable "bigquery_dataset_ids" {
  description = "Spec §13.1: cairn_raw, cairn_curated, cairn_consumption."
  type        = list(string)
  default     = ["cairn_raw", "cairn_curated", "cairn_consumption"]
}

variable "access_log_bucket_name" {
  description = "Destination bucket (from cairn-observability) that these buckets' access logs are written to."
  type        = string
}

variable "gcs_bucket_names" {
  description = "Spec §13.1: cairn-raw-{env}, cairn-artifacts-{env}, cairn-evidence-{env}. The evidence bucket is provisioned by cairn-evidence instead, with retention lock — not listed here."
  type        = list(string)
  default     = ["raw", "artifacts"]
}

variable "labels" {
  type    = map(string)
  default = {}
}

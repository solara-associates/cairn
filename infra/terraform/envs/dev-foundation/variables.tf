variable "project_id" {
  description = "GCP project ID. Must be solara-cairn-dev -- see README.md."
  type        = string
}

variable "region" {
  description = "ADR-016/docs/residency/uk-residency-matrix.md: UK-only, europe-west2 (London)."
  type        = string
  default     = "europe-west2"
}

variable "project_id" {
  description = "GCP project ID the network is created in."
  type        = string
}

variable "region" {
  description = "Primary region for regional resources (spec §13.1: europe-west2 for the hosted SaaS profile)."
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod) used in resource naming and labels."
  type        = string
}

variable "subnet_cidr" {
  description = "Primary CIDR range for the environment's Cloud Run / VPC connector subnet."
  type        = string
}

variable "private_service_cidr_range" {
  description = "Allocated /16-or-smaller range reserved for Private Service Access (Cloud SQL, Memorystore)."
  type        = string
  default     = "10.100.0.0/16"
}

variable "labels" {
  description = "Common labels applied to taggable network resources."
  type        = map(string)
  default     = {}
}

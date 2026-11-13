variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "environment" {
  type = string
}

variable "vpc_connector_subnet_id" {
  description = "Subnet (from cairn-network) Cloud Run services egress through for private Cloud SQL / Memorystore access."
  type        = string
}

variable "services" {
  description = <<-EOT
    Spec §13.1 Cloud Run services: cairn-api, cairn-worker, cairn-mcp-gateway,
    cairn-console. Key is the short service name; value configures image,
    scaling and the Workload Identity service account email it runs as.
  EOT
  type = map(object({
    image              = string
    service_account    = string
    min_instance_count = number
    max_instance_count = number
    container_port     = number
    ingress            = string # one of: INGRESS_TRAFFIC_ALL, INGRESS_TRAFFIC_INTERNAL_ONLY, INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER
  }))
}

variable "jobs" {
  description = <<-EOT
    Spec §13.1 Cloud Run jobs: cairn-scheduler, cairn-ingest-job, cairn-assess-job,
    cairn-transform-job.
  EOT
  type = map(object({
    image           = string
    service_account = string
  }))
}

variable "labels" {
  type    = map(string)
  default = {}
}

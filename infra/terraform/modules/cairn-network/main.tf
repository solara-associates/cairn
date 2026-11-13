# VPC, subnet, private service access and baseline firewall for one environment.
# Spec §13.3 "cairn-network": VPC, subnets, private service access, egress, firewall.

resource "google_compute_network" "cairn" {
  project                 = var.project_id
  name                    = "cairn-${var.environment}"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
}

resource "google_compute_subnetwork" "primary" {
  project                  = var.project_id
  name                     = "cairn-${var.environment}-${var.region}"
  region                   = var.region
  network                  = google_compute_network.cairn.id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_5_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

# Reserved range for Private Service Access, used by Cloud SQL and Memorystore
# so neither is reachable from outside the VPC.
resource "google_compute_global_address" "private_service_range" {
  project       = var.project_id
  name          = "cairn-${var.environment}-psa-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.cairn.id
}

resource "google_service_networking_connection" "private_service_access" {
  network                 = google_compute_network.cairn.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.private_service_range.name]
}

# Deny all ingress by default; narrow allow rules live in cairn-runtime /
# cairn-guardrails alongside the resources that need them.
resource "google_compute_firewall" "deny_all_ingress" {
  project   = var.project_id
  name      = "cairn-${var.environment}-deny-all-ingress"
  network   = google_compute_network.cairn.id
  direction = "INGRESS"
  priority  = 65534

  deny {
    protocol = "all"
  }

  source_ranges = ["0.0.0.0/0"]
}

resource "google_compute_firewall" "allow_internal" {
  project   = var.project_id
  name      = "cairn-${var.environment}-allow-internal"
  network   = google_compute_network.cairn.id
  direction = "INGRESS"
  priority  = 1000

  allow {
    protocol = "all"
  }

  source_ranges = [var.subnet_cidr]
}

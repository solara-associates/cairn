# Cloud Run services and jobs for one environment.
# Spec §13.3 "cairn-runtime": Cloud Run services/jobs, scaling, probes, ingress.

resource "google_cloud_run_v2_service" "service" {
  for_each = var.services

  project  = var.project_id
  name     = "cairn-${each.key}-${var.environment}"
  location = var.region
  ingress  = each.value.ingress

  template {
    service_account = each.value.service_account

    scaling {
      min_instance_count = each.value.min_instance_count
      max_instance_count = each.value.max_instance_count
    }

    vpc_access {
      network_interfaces {
        subnetwork = var.vpc_connector_subnet_id
      }
      egress = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = each.value.image

      ports {
        container_port = each.value.container_port
      }

      startup_probe {
        http_get {
          path = "/healthz"
        }
        period_seconds    = 5
        failure_threshold = 6
      }

      liveness_probe {
        http_get {
          path = "/readyz"
        }
        period_seconds = 15
      }
    }

    labels = var.labels
  }
}

resource "google_cloud_run_v2_job" "job" {
  for_each = var.jobs

  project  = var.project_id
  name     = "cairn-${each.key}-${var.environment}"
  location = var.region

  template {
    template {
      service_account = each.value.service_account

      containers {
        image = each.value.image
      }

      vpc_access {
        network_interfaces {
          subnetwork = var.vpc_connector_subnet_id
        }
        egress = "PRIVATE_RANGES_ONLY"
      }
    }

    labels = var.labels
  }
}

# Log sinks, metrics, dashboards, alerts, SLOs.
# Spec §13.3 "cairn-observability". Alerting and SLO-burn dashboards are
# deliberately not built in this skeleton — they need real RED-metric and
# trace data from a running service first (spec §14.1) — only the sink and
# notification channel that later alert policies attach to exist here.

# Shared access-log target for every other module's buckets (cairn-data,
# cairn-evidence) — GCS access logging needs a destination bucket, and having
# every module create its own would multiply low-value buckets per environment.
resource "google_storage_bucket" "access_logs" {
  project                     = var.project_id
  name                        = "cairn-access-logs-${var.environment}"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }

  # checkov:skip=CKV_GCP_62: this bucket IS the access-log destination for
  # every other bucket in the environment; GCS cannot log a bucket to itself.
}

resource "google_logging_project_sink" "cairn" {
  project                = var.project_id
  name                   = "cairn-${var.environment}-sink"
  destination            = var.log_sink_destination
  unique_writer_identity = true

  filter = "resource.type=\"cloud_run_revision\" OR resource.type=\"cloud_run_job\""
}

resource "google_monitoring_notification_channel" "oncall" {
  project      = var.project_id
  display_name = "CAIRN ${var.environment} on-call"
  type         = "email"

  labels = {
    email_address = var.notification_email
  }
}

resource "google_monitoring_alert_policy" "job_failures" {
  project      = var.project_id
  display_name = "CAIRN ${var.environment}: job failures"
  combiner     = "OR"

  conditions {
    display_name = "Cloud Run job execution failed"

    condition_threshold {
      filter          = "resource.type=\"cloud_run_job\" AND metric.type=\"run.googleapis.com/job/completed_execution_count\" AND metric.label.result=\"failed\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_COUNT"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.oncall.id]
}

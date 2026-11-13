# Cloud SQL, BigQuery datasets and object storage for one environment.
# Spec §13.3 "cairn-data": Cloud SQL, BigQuery datasets, GCS buckets, retention.
# The evidence bucket (immutable, retention-locked) is cairn-evidence's resource,
# not this module's — evidence has stricter, non-negotiable retention semantics.

resource "google_sql_database_instance" "cairn" {
  project = var.project_id
  name    = "cairn-${var.environment}"
  region  = var.region
  # Pinned to match the version already tested against in CI and R0-08's
  # migrations (postgres:16 service container) — not the newest available
  # major version, which would be an untested, unrelated upgrade here.
  # checkov:skip=CKV_GCP_79: see comment above.
  database_version = "POSTGRES_16"

  settings {
    tier              = var.cloudsql_tier
    availability_type = var.cloudsql_availability_type

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }

    ip_configuration {
      ipv4_enabled    = false
      private_network = var.network_id
      ssl_mode        = "TRUSTED_CLIENT_CERTIFICATE_REQUIRED"
    }

    # IAM database authentication in place of long-lived database passwords
    # (spec §13.1 acceptance: "no long-lived secrets").
    database_flags {
      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    # Audit-grade query logging — the evidence/audit chain (ADR-008, R0-10)
    # needs to be able to reconstruct what happened at the database.
    database_flags {
      name  = "log_disconnections"
      value = "on"
    }

    database_flags {
      name  = "log_connections"
      value = "on"
    }

    database_flags {
      name  = "log_hostname"
      value = "on"
    }

    database_flags {
      name  = "log_lock_waits"
      value = "on"
    }

    database_flags {
      name  = "log_duration"
      value = "on"
    }

    database_flags {
      name  = "log_statement"
      value = "ddl"
    }

    database_flags {
      name  = "log_min_messages"
      value = "error"
    }

    database_flags {
      name  = "log_min_error_statement"
      value = "error"
    }

    database_flags {
      name  = "log_checkpoints"
      value = "on"
    }

    database_flags {
      name  = "cloudsql.enable_pgaudit"
      value = "on"
    }
  }

  deletion_protection = true
}

resource "google_bigquery_dataset" "cairn" {
  for_each = toset(var.bigquery_dataset_ids)

  project    = var.project_id
  dataset_id = each.value
  location   = var.region
  labels     = var.labels

  # checkov:skip=CKV_GCP_81: CMEK on BigQuery datasets is deferred — the only
  # customer-managed key this skeleton provisions is the evidence signing key
  # (cairn-evidence); a data-at-rest CMEK key and its rotation policy is a
  # separate decision, not yet made. Tracked as outstanding in README.md.
}

resource "google_storage_bucket" "cairn" {
  for_each = toset(var.gcs_bucket_names)

  project                     = var.project_id
  name                        = "cairn-${each.value}-${var.environment}"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  labels                      = var.labels

  versioning {
    enabled = true
  }

  logging {
    log_bucket = var.access_log_bucket_name
  }
}

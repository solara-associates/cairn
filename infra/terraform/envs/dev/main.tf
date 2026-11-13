locals {
  environment = "dev"

  labels = {
    environment = local.environment
    managed_by  = "terraform"
    system      = "cairn"
  }

  # Spec §13.1 Cloud Run services and jobs, and the least-privilege roles each
  # workload needs. Dev keeps every service min_instance_count = 0 to cost
  # nothing at idle; staging/prod size this per the spec's NFR-001 target.
  workload_roles = {
    api           = ["roles/cloudsql.client", "roles/pubsub.publisher"]
    worker        = ["roles/cloudsql.client", "roles/pubsub.subscriber", "roles/bigquery.dataEditor"]
    mcp-gateway   = ["roles/cloudsql.client"]
    scheduler     = ["roles/pubsub.publisher"]
    ingest-job    = ["roles/cloudsql.client", "roles/bigquery.dataEditor", "roles/storage.objectAdmin"]
    assess-job    = ["roles/cloudsql.client", "roles/bigquery.dataEditor"]
    transform-job = ["roles/cloudsql.client", "roles/storage.objectAdmin"]
  }
}

module "network" {
  source = "../../modules/cairn-network"

  project_id  = var.project_id
  region      = var.region
  environment = local.environment
  subnet_cidr = "10.10.0.0/24"
  labels      = local.labels
}

module "iam" {
  source = "../../modules/cairn-iam"

  project_id                = var.project_id
  environment               = local.environment
  workload_service_accounts = local.workload_roles
}

module "data" {
  source = "../../modules/cairn-data"

  project_id                        = var.project_id
  region                            = var.region
  environment                       = local.environment
  network_id                        = module.network.network_id
  private_service_access_connection = module.network.private_service_access_connection
  access_log_bucket_name            = module.observability.access_log_bucket_name
  cloudsql_tier                     = "db-g1-small"
  cloudsql_availability_type        = "ZONAL"
  labels                            = local.labels
}

module "events" {
  source = "../../modules/cairn-events"

  project_id  = var.project_id
  environment = local.environment
  labels      = local.labels

  topics = {
    "estate.changed" = {
      subscribers           = ["assess-job"]
      ack_deadline_seconds  = 30
      max_delivery_attempts = 5
    }
    "evidence.recorded" = {
      subscribers           = ["worker"]
      ack_deadline_seconds  = 30
      max_delivery_attempts = 5
    }
  }
}

module "runtime" {
  source = "../../modules/cairn-runtime"

  project_id              = var.project_id
  region                  = var.region
  environment             = local.environment
  vpc_connector_subnet_id = module.network.subnet_id
  labels                  = local.labels

  services = {
    api = {
      image              = var.workload_image
      service_account    = module.iam.service_account_emails["api"]
      min_instance_count = 0
      max_instance_count = 2
      container_port     = 8080
      ingress            = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
    }
    worker = {
      image              = var.workload_image
      service_account    = module.iam.service_account_emails["worker"]
      min_instance_count = 0
      max_instance_count = 2
      container_port     = 8080
      ingress            = "INGRESS_TRAFFIC_INTERNAL_ONLY"
    }
    mcp-gateway = {
      image              = var.workload_image
      service_account    = module.iam.service_account_emails["mcp-gateway"]
      min_instance_count = 0
      max_instance_count = 1
      container_port     = 8080
      ingress            = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
    }
  }

  jobs = {
    scheduler = {
      image           = var.workload_image
      service_account = module.iam.service_account_emails["scheduler"]
    }
    ingest-job = {
      image           = var.workload_image
      service_account = module.iam.service_account_emails["ingest-job"]
    }
    assess-job = {
      image           = var.workload_image
      service_account = module.iam.service_account_emails["assess-job"]
    }
    transform-job = {
      image           = var.workload_image
      service_account = module.iam.service_account_emails["transform-job"]
    }
  }
}

module "observability" {
  source = "../../modules/cairn-observability"

  project_id           = var.project_id
  region               = var.region
  environment          = local.environment
  notification_email   = var.notification_email
  log_sink_destination = "bigquery.googleapis.com/projects/${var.project_id}/datasets/cairn_raw"
}

module "guardrails" {
  source = "../../modules/cairn-guardrails"

  project_id                  = var.project_id
  environment                 = local.environment
  billing_account_id          = var.billing_account_id
  monthly_budget_amount_units = var.monthly_budget_amount_units
  allowed_resource_locations  = [var.region]
  notification_channel_ids    = [module.observability.notification_channel_id]
}

module "evidence" {
  source = "../../modules/cairn-evidence"

  project_id                   = var.project_id
  region                       = var.region
  environment                  = local.environment
  signer_service_account_email = module.iam.service_account_emails["worker"]
  access_log_bucket_name       = module.observability.access_log_bucket_name
  retention_period_seconds     = var.evidence_retention_period_seconds
}

module "connections" {
  source = "../../modules/cairn-connections"

  project_id  = var.project_id
  environment = local.environment
}
